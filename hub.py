import json
import os
import queue
import statistics
import re
import threading
import traceback
import uuid
from collections import deque
import time
from pathlib import Path

import compact
from fsutil import append_private, atomic_write
import oauth
from sessions import PROTOCOL_VERSION, AuthRequired, RpcError, SessionExpired, open_session
from version import VERSION

SEPARATOR = "__"
SUPPORTED_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
RESTART_DELAYS = (2, 4, 8, 16, 32)
STABLE_AFTER = 60
ON_DEMAND_IDLE = 600


def runtime_key(entry, pass_environment):
    relevant = {k: v for k, v in (entry or {}).items() if k not in ("description", "tags", "disabledTools", "enabledTools")}
    return json.dumps([relevant, pass_environment], sort_keys=True)


def labelled(upstream, item):
    base = item.get("title") or (item.get("annotations") or {}).get("title") \
        or re.sub(r"(?<=[a-z0-9])(?=[A-Z])|[_-]+", " ", item["name"]).capitalize()
    title = f"{upstream.name}: {base}"
    result = {**item, "name": f"{upstream.prefix}{SEPARATOR}{item['name']}", "title": title}
    if (item.get("annotations") or {}).get("title"):
        result["annotations"] = {**item["annotations"], "title": title}
    return result


def prefix_of(name):
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def summary(upstream):
    tools = upstream.catalog["tools"]
    return upstream.server_info.get("description") or upstream.instructions.strip().split("\n")[0][:300] \
        or ", ".join(t["name"] for t in tools[:6]) + (" …" if len(tools) > 6 else "")


class JsonRpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Upstream:
    def __init__(self, name, entry, key, on_change=None):
        self.name = name
        self.on_change = on_change
        self.entry = entry
        self.key = key
        self.prefix = prefix_of(name)
        self.session = None
        self.state = "starting"
        self.error = None
        self.capabilities = {}
        self.catalog = {"tools": [], "resources": [], "resourceTemplates": [], "prompts": []}
        self.stale = False
        self.server_info = {}
        self.instructions = ""
        self.challenge = None
        self.pass_environment = True
        self.started_at = None
        self.restart_lock = threading.Lock()

    def start(self, pass_environment):
        self.pass_environment = pass_environment
        try:
            self.session = open_session(self.name, self.entry, pass_environment, "mcp-hub")
            self.session.on_notification = self._on_notification
            info = self.session.initialize()
            self.capabilities = info.get("capabilities", {})
            self.server_info = info.get("serverInfo") or {}
            self.instructions = info.get("instructions") or ""
            self.refresh()
            self.state = "running"
            self.error = None
            self.started_at = time.time()
        except AuthRequired as e:
            self.challenge = e.challenge
            self.error = "Sign-in required"
            self.state = "auth"
            self.close()
        except Exception as e:
            self.error = (str(e).splitlines() or [type(e).__name__])[0] + self._stderr_tail()
            self.state = "error"
            self.close()

    def _stderr_tail(self):
        stderr = [x["data"] for x in self.session.log if x["kind"] in ("stderr", "error")] if self.session else []
        return f" – {stderr[-1]}" if stderr else ""

    def _on_notification(self, message):
        if message["method"].endswith("/list_changed"):
            self.stale = True
            if self.on_change:
                self.on_change()

    def refresh(self):
        self.stale = False
        lists = [("tools", "tools/list", "tools"), ("resources", "resources/list", "resources"),
                 ("resources", "resources/templates/list", "resourceTemplates"), ("prompts", "prompts/list", "prompts")]
        for capability, method, key in lists:
            if capability in self.capabilities:
                try:
                    self.catalog[key] = self.session.list_all(method, key)
                except (RpcError, AttributeError, TypeError):
                    pass

    def blocked(self, disabled=None):
        names = set((self.entry.get("disabledTools") or []) if disabled is None else disabled)
        allowed = self.entry.get("enabledTools")
        if allowed:
            names |= {t["name"] for t in self.catalog["tools"]} - set(allowed)
        return names

    def tools(self, disabled=None):
        blocked = self.blocked(disabled)
        return [t for t in self.catalog["tools"] if t["name"] not in blocked]

    def alive(self):
        return self.session is not None and self.session.alive()

    def mark_crashed(self):
        self.state = "error"
        self.error = "Server stopped unexpectedly" + self._stderr_tail()
        self.close()

    def request(self, method, params):
        if not self.alive():
            raise RpcError(f"Server “{self.name}” is not running")
        session = self.session
        try:
            return session.request(method, params, timeout=300)
        except AuthRequired:
            if not oauth.access_token(self.name, force_refresh=True):
                self.close()
                self.state, self.error = "auth", "Sign-in required"
                raise
            self._restart_session(session)
        except SessionExpired:
            self._restart_session(session)
        return self.session.request(method, params, timeout=300)

    def _restart_session(self, failed):
        with self.restart_lock:
            if self.session is failed:
                failed.close()
                self.start(self.pass_environment)
        if self.state != "running":
            raise RpcError(f"Server “{self.name}”: {self.error}")

    def close(self):
        if self.session:
            self.session.close()


class Usage:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        try:
            self.data = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def record(self, server):
        with self.lock:
            entry = self.data.setdefault(server, {"count": 0, "last": None})
            entry["count"] += 1
            entry["last"] = time.time()
            atomic_write(self.path, json.dumps(self.data, indent=2))

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.data))


class CallLog:
    def __init__(self, path, keep=5000):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.entries = deque(maxlen=keep)
        self.appended = 0
        try:
            for line in self.path.read_text().splitlines()[-keep:]:
                try:
                    self.entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        except FileNotFoundError:
            pass

    def record(self, entry):
        with self.lock:
            self.entries.append(entry)
            self.appended += 1
            if self.appended % 500 == 0:
                atomic_write(self.path, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.entries))
            else:
                append_private(self.path, json.dumps(entry, ensure_ascii=False) + "\n")

    def recent(self, limit):
        with self.lock:
            return list(self.entries)[-limit:][::-1]

    def stats(self, days=14):
        with self.lock:
            entries = list(self.entries)
        today = time.localtime()
        midnight = time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, 0, 0, -1))
        buckets = [time.strftime("%Y-%m-%d", time.localtime(midnight - 86400 * i)) for i in reversed(range(days))]
        per_day = {day: {"day": day, "ok": 0, "errors": 0} for day in buckets}
        servers, tools = {}, {}
        for entry in entries:
            day = time.strftime("%Y-%m-%d", time.localtime(entry["t"]))
            if day in per_day:
                per_day[day]["ok" if entry.get("ok") else "errors"] += 1
            for group, key in ((servers, entry["server"]), (tools, (entry["server"], entry["target"]))):
                bucket = group.setdefault(key, {"calls": 0, "errors": 0, "ms": [], "last": 0})
                bucket["calls"] += 1
                bucket["errors"] += 0 if entry.get("ok") else 1
                bucket["ms"].append(entry.get("ms", 0))
                bucket["last"] = max(bucket["last"], entry["t"])

        def summary(bucket):
            ms = sorted(bucket["ms"])
            return {"calls": bucket["calls"], "errors": bucket["errors"], "last": bucket["last"],
                    "median": round(statistics.median(ms)) if ms else 0,
                    "p95": ms[min(len(ms) - 1, int(len(ms) * 0.95))] if ms else 0}

        durations = [entry.get("ms", 0) for entry in entries]
        return {
            "since": entries[0]["t"] if entries else None,
            "kept": self.entries.maxlen,
            "total": len(entries),
            "errors": sum(1 for entry in entries if not entry.get("ok")),
            "median": round(statistics.median(durations)) if durations else 0,
            "clients": len({entry.get("client") for entry in entries}),
            "days": list(per_day.values()),
            "servers": sorted(({"server": name, **summary(b)} for name, b in servers.items()), key=lambda s: -s["calls"]),
            "slowest": sorted(({"server": key[0], "tool": key[1], **summary(b)} for key, b in tools.items()),
                              key=lambda t: -t["p95"])[:5],
        }


class Clients:
    def __init__(self, path, keep=300):
        self.path = Path(path)
        self.keep = keep
        self.lock = threading.Lock()
        self.active = {}
        try:
            self.sessions = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self.sessions = {}

    def register(self, client_info, user_agent, profile=None, mode=None):
        session_id = uuid.uuid4().hex
        now = time.time()
        with self.lock:
            self.sessions[session_id] = {
                "name": (client_info or {}).get("name") or user_agent or "unknown",
                "version": (client_info or {}).get("version"),
                "since": now,
            }
            self.active[session_id] = {"profile": profile, "mode": mode, "lastSeen": now, "requests": 1, "calls": 0, "streams": 0}
            while len(self.sessions) > self.keep:
                self.sessions.pop(next(iter(self.sessions)))
            atomic_write(self.path, json.dumps(self.sessions))
        return session_id

    def valid(self, session_id):
        return not session_id or session_id in self.active

    def end(self, session_id):
        with self.lock:
            self.active.pop(session_id, None)

    def touch(self, session_id, call=False):
        with self.lock:
            activity = self.active.get(session_id or "")
            if activity:
                activity["lastSeen"] = time.time()
                activity["requests"] += 1
                activity["calls"] += call

    def stream(self, session_id, delta):
        with self.lock:
            activity = self.active.get(session_id or "")
            if activity:
                activity["streams"] = max(0, activity["streams"] + delta)
                activity["lastSeen"] = time.time()

    def snapshot(self):
        with self.lock:
            rows = [{"id": sid[:8], "name": self.sessions[sid]["name"], "version": self.sessions[sid].get("version"),
                     "since": self.sessions[sid]["since"], **activity}
                    for sid, activity in self.active.items() if sid in self.sessions]
        return sorted(rows, key=lambda r: (not r["streams"], -r["lastSeen"]))

    def lookup(self, session_id, user_agent):
        session = self.sessions.get(session_id or "")
        if session:
            return session["name"]
        return f"{user_agent.split('/')[0]} (no session)" if user_agent else "unknown"


def preview(value, limit):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + " …"


def first_text(result):
    for block in (result or {}).get("content") or (result or {}).get("contents") or []:
        if block.get("text"):
            return block["text"]
    return ""


class Hub:
    def __init__(self, load_config, load_settings, state_dir, load_profiles=lambda: {"profiles": {}}):
        self.load_config = load_config
        self.load_settings = load_settings
        self.load_profiles = load_profiles
        self.listeners = {}
        self.listeners_lock = threading.Lock()
        self.signature = None
        self.usage = Usage(Path(state_dir) / "usage.json")
        self.calls = CallLog(Path(state_dir) / "calls.jsonl")
        self.clients = Clients(Path(state_dir) / "clients.json")
        self.lock = threading.Lock()
        self.upstreams = {}
        self.restarts = {}
        self.on_demand = {}
        self.demand_lock = threading.Lock()
        self.notify_lock = threading.Lock()
        self.idle_after = float(os.environ.get("MCP_HUB_ON_DEMAND_IDLE") or ON_DEMAND_IDLE)

    def _demand(self, profile):
        saved = self.load_profiles()["profiles"].get(profile)
        if not saved:
            return
        config = self.load_config()["mcpServers"]
        now = time.time()
        with self.demand_lock:
            for name, wanted in saved["servers"].items():
                entry = config.get(name) or {}
                if wanted.get("enabled") and entry.get("enabled", True) is False and (entry.get("command") or entry.get("url")):
                    self.on_demand[name] = now

    def _expire_on_demand(self):
        cutoff = time.time() - self.idle_after
        with self.demand_lock:
            expired = [name for name, used in self.on_demand.items() if used < cutoff]
            for name in expired:
                del self.on_demand[name]
        return bool(expired)

    def _schedule_restart(self, upstream, now):
        info = self.restarts.setdefault(upstream.name, {"count": 0, "failures": 0, "retryAt": None, "gaveUp": False})
        if info["retryAt"] or info["gaveUp"]:
            return
        if upstream.started_at is not None and now - upstream.started_at >= STABLE_AFTER:
            info["failures"] = 0
        info["failures"] += 1
        if info["failures"] > len(RESTART_DELAYS):
            info["gaveUp"] = True
        else:
            info["retryAt"] = now + RESTART_DELAYS[info["failures"] - 1]

    def _needs_attention(self):
        now = time.time()
        for name, upstream in list(self.upstreams.items()):
            info = self.restarts.get(name) or {}
            if upstream.state == "running" and not upstream.alive():
                return True
            if upstream.state == "error" and not info.get("gaveUp") and (not info.get("retryAt") or now >= info["retryAt"]):
                return True
        return False

    def supervise(self, interval=2):
        while True:
            time.sleep(interval)
            try:
                if self._expire_on_demand() or self._needs_attention():
                    self.sync()
            except Exception:
                traceback.print_exc()

    def supervise_in_background(self):
        threading.Thread(target=self.supervise, daemon=True).start()

    def sync(self, wait=150):
        with self.lock:
            pass_environment = self.load_settings()["passEnvironment"]
            config = self.load_config()["mcpServers"]
            wanted = {
                name: entry for name, entry in config.items()
                if entry.get("enabled", True) and (entry.get("command") or entry.get("url"))
            }
            with self.demand_lock:
                for name in list(self.on_demand):
                    entry = config.get(name) or {}
                    if name in wanted or not (entry.get("command") or entry.get("url")):
                        del self.on_demand[name]
                    else:
                        wanted[name] = entry
            now = time.time()
            for name, upstream in list(self.upstreams.items()):
                key = runtime_key(wanted.get(name), pass_environment)
                if name not in wanted or upstream.key != key:
                    upstream.close()
                    del self.upstreams[name]
                    self.restarts.pop(name, None)
                    continue
                if upstream.state == "running" and not upstream.alive():
                    upstream.mark_crashed()
                if upstream.state != "error":
                    continue
                self._schedule_restart(upstream, now)
                info = self.restarts[name]
                if info["retryAt"] and now >= info["retryAt"]:
                    info["retryAt"] = None
                    info["count"] += 1
                    info["lastError"] = upstream.error
                    upstream.close()
                    del self.upstreams[name]
            starting = []
            for name, entry in wanted.items():
                if name in self.upstreams:
                    self.upstreams[name].entry = entry
                else:
                    upstream = Upstream(name, entry, runtime_key(entry, pass_environment), self.sync_in_background)
                    self.upstreams[name] = upstream
                    starting.append(upstream)
            stale = [u for u in self.upstreams.values() if u.state == "running" and u.stale]
        threads = [threading.Thread(target=self._start, args=(u, pass_environment), daemon=True) for u in starting]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + wait
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        for upstream in stale:
            upstream.refresh()
        running = self._running()
        self._notify_if_changed(running)
        return running

    def _await_start(self, prefixed, running, timeout=60):
        if prefixed in (compact.SEARCH, compact.DESCRIBE, compact.CALL):
            prefixed = ""
        if not prefixed or any(prefixed.startswith(u.prefix + SEPARATOR) for u in running):
            return False
        starting = [u for u in list(self.upstreams.values())
                    if u.state == "starting" and prefixed.startswith(u.prefix + SEPARATOR)]
        deadline = time.monotonic() + timeout
        while starting and any(u.state == "starting" for u in starting) and time.monotonic() < deadline:
            time.sleep(0.2)
        return bool(starting)

    def _running(self):
        return [u for u in list(self.upstreams.values()) if u.state == "running"]

    def _start(self, upstream, pass_environment):
        upstream.start(pass_environment)
        with self.lock:
            if self.upstreams.get(upstream.name) is not upstream:
                upstream.close()
                return
        self._notify_if_changed(self._running())

    def reconnect(self, name):
        with self.lock:
            self.restarts.pop(name, None)
            upstream = self.upstreams.pop(name, None)
            if upstream:
                upstream.close()
        self.sync_in_background()

    def challenge(self, name):
        upstream = self.upstreams.get(name)
        return upstream.challenge if upstream else None

    def sync_in_background(self):
        threading.Thread(target=self.sync, daemon=True).start()

    def subscribe(self, client):
        listener = queue.Queue()
        with self.listeners_lock:
            self.listeners[listener] = client
        return listener

    def unsubscribe(self, listener):
        with self.listeners_lock:
            self.listeners.pop(listener, None)

    def live_clients(self):
        with self.listeners_lock:
            return sorted(self.listeners.values())

    def _notify_if_changed(self, running):
        running = [u for u in running if u.name not in self.on_demand]
        with self.notify_lock:
            self._notify(running)

    def _notify(self, running):
        signature = json.dumps([
            [(u.name, sorted(t["name"] for t in u.tools()), sorted(p["name"] for p in u.catalog["prompts"]),
              sorted(r["uri"] for r in u.catalog["resources"]), len(u.catalog["resourceTemplates"]))
             for u in sorted(running, key=lambda u: u.name)],
            self.load_profiles().get("profiles"),
        ], sort_keys=True)
        changed = self.signature is not None and signature != self.signature
        self.signature = signature
        if not changed:
            return
        with self.listeners_lock:
            for listener in self.listeners:
                for kind in ("tools", "prompts", "resources"):
                    listener.put({"jsonrpc": "2.0", "method": f"notifications/{kind}/list_changed"})

    def close(self):
        with self.lock:
            for upstream in self.upstreams.values():
                upstream.close()
            self.upstreams.clear()

    def status(self):
        return {
            name: {
                "state": u.state,
                "error": u.error,
                "summary": summary(u),
                **{k: len(v) for k, v in u.catalog.items()},
                "tools": len(u.tools()),
                "toolsTotal": len(u.catalog["tools"]),
                **self._restart_status(name),
                **({"onDemand": True} if name in self.on_demand else {}),
                **({"oauth": oauth.status(name)} if u.entry.get("url") else {}),
            }
            for name, u in list(self.upstreams.items())
        }

    def _restart_status(self, name):
        info = self.restarts.get(name)
        if not info:
            return {}
        return {"restarts": info["count"], "retryAt": info["retryAt"], "gaveUp": info["gaveUp"],
                "lastError": info.get("lastError")}

    def tools(self, name):
        upstream = self.upstreams.get(name)
        if not upstream:
            return None
        blocked = upstream.blocked()
        return [{"name": t["name"], "title": t.get("title") or (t.get("annotations") or {}).get("title"),
                 "description": (t.get("description") or "").strip().split("\n")[0][:240],
                 "enabled": t["name"] not in blocked}
                for t in upstream.catalog["tools"]]

    def _view(self, running, profile):
        if not profile:
            return {u: set(u.entry.get("disabledTools") or []) for u in running if u.name not in self.on_demand}
        saved = self.load_profiles()["profiles"].get(profile)
        if saved is None:
            raise JsonRpcError(-32602, f"Unknown profile: {profile}")
        view = {}
        for upstream in running:
            wanted = saved["servers"].get(upstream.name)
            if wanted is None:
                if upstream.name not in self.on_demand:
                    view[upstream] = set(upstream.entry.get("disabledTools") or [])
            elif wanted["enabled"]:
                view[upstream] = set(wanted["disabledTools"])
        return view

    def _route(self, running, prefixed):
        for upstream in sorted(running, key=lambda u: -len(u.prefix)):
            if prefixed.startswith(upstream.prefix + SEPARATOR):
                return upstream, prefixed[len(upstream.prefix) + len(SEPARATOR):]
        raise JsonRpcError(-32602, f"Unknown: {prefixed}")

    def handle(self, method, params, client="unknown", profile=None, mode=None):
        params = params or {}
        if profile and method not in ("ping", "logging/setLevel"):
            self._demand(profile)
        if method == "initialize":
            if profile and profile not in self.load_profiles()["profiles"]:
                raise JsonRpcError(-32602, f"Unknown profile: {profile}")
            requested = params.get("protocolVersion")
            result = {
                "protocolVersion": requested if requested in SUPPORTED_VERSIONS else PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": True}, "resources": {"listChanged": True},
                                 "prompts": {"listChanged": True}, "logging": {}},
                "serverInfo": {"name": "mcp-hub", "version": VERSION},
                "instructions": "Bundles several MCP servers. Tool and prompt names carry the server name as a prefix (server__tool).",
            }
            if mode == "compact":
                view = self._view(self.sync(), profile)
                result["instructions"] = compact.instructions(
                    {u.name: (u.entry.get("description") or summary(u)).split("\n")[0][:200] for u in view},
                    sum(len(u.tools(disabled)) for u, disabled in view.items()))
            return result
        if method in ("ping", "logging/setLevel"):
            return {}

        running = self.sync()
        if method in ("tools/call", "prompts/get") and self._await_start(params.get("name", ""), running):
            running = self._running()
        view = self._view(running, profile)
        running = list(view)
        if method == "tools/list" and mode == "compact":
            return {"tools": compact.meta_tools(sorted(u.name for u in running))}
        if method == "tools/call" and mode == "compact" and params.get("name") in (compact.SEARCH, compact.DESCRIBE, compact.CALL):
            return self._compact_call(view, params, client, profile)
        if method == "tools/list":
            return {"tools": [labelled(u, t) for u, disabled in view.items() for t in u.tools(disabled)]}
        if method == "prompts/list":
            return {"prompts": [labelled(u, p) for u in running for p in u.catalog["prompts"]]}
        if method == "resources/list":
            return {"resources": [r for u in running for r in u.catalog["resources"]]}
        if method == "resources/templates/list":
            return {"resourceTemplates": [t for u in running for t in u.catalog["resourceTemplates"]]}
        if method == "tools/call":
            upstream, name = self._route(running, params.get("name", ""))
            if name in upstream.blocked(view[upstream]):
                raise JsonRpcError(-32602, f"Tool disabled in the hub: {params.get('name')}")
            return self._forward(upstream, "tools/call", {**params, "name": name}, name, client)
        if method == "prompts/get":
            upstream, name = self._route(running, params.get("name", ""))
            return self._forward(upstream, "prompts/get", {**params, "name": name}, name, client)
        if method == "resources/read":
            uri = params.get("uri", "")
            for upstream in running:
                if any(r["uri"] == uri for r in upstream.catalog["resources"]):
                    return self._forward(upstream, "resources/read", params, uri, client)
            for upstream in running:
                for template in upstream.catalog["resourceTemplates"]:
                    if uri.startswith(template["uriTemplate"].split("{")[0]):
                        return self._forward(upstream, "resources/read", params, uri, client)
            raise JsonRpcError(-32002, f"Resource not found: {uri}")
        raise JsonRpcError(-32601, f"Method not supported: {method}")

    def _compact_call(self, view, params, client, profile):
        name, args = params["name"], params.get("arguments") or {}
        tools = [labelled(u, t) for u, disabled in view.items() for t in u.tools(disabled)]
        if name == compact.SEARCH:
            server = next((u.prefix for u in view if u.name == args.get("server")), args.get("server"))
            about = {u.prefix: f"{u.entry.get('description') or ''} {summary(u)}" for u in view}
            found = compact.search(tools, args.get("query", ""), server, args.get("limit"), about)
            return compact.text(compact.format_results(found))
        if name == compact.DESCRIBE:
            tool = next((t for t in tools if t["name"] == args.get("name")), None)
            if not tool:
                return compact.text(f"Unknown tool: {args.get('name')}. Use {compact.SEARCH} to find it.", error=True)
            return compact.text(compact.describe(tool))
        try:
            return self.handle("tools/call", {"name": args.get("name", ""), "arguments": args.get("arguments") or {}},
                               client, profile)
        except JsonRpcError as e:
            return compact.text(f"{e} – use {compact.SEARCH} to find the right tool name.", error=True)

    def _forward(self, upstream, method, params, target, client):
        self.usage.record(upstream.name)
        entry = {
            "t": time.time(), "client": client, "server": upstream.name,
            "kind": {"tools/call": "tool", "prompts/get": "prompt"}.get(method, "resource"),
            "target": target,
            "args": preview(params.get("arguments", {}), 4000) if method != "resources/read" else "",
        }
        started = time.monotonic()
        try:
            result = upstream.request(method, params)
            entry["ok"] = not result.get("isError")
            entry["result"] = preview(first_text(result), 600)
            return result
        except RpcError as e:
            entry["ok"] = False
            entry["result"] = str(e)
            if method == "tools/call":
                return {"content": [{"type": "text", "text": str(e)}], "isError": True}
            raise JsonRpcError(-32603, str(e))
        finally:
            entry["ms"] = round((time.monotonic() - started) * 1000)
            self.calls.record(entry)
