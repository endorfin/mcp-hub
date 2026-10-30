import json
import queue
import statistics
import re
import threading
import uuid
from collections import deque
import time
from pathlib import Path

import compact
import oauth
from inspector import PROTOCOL_VERSION, VERSION, AuthRequired, RpcError, open_session

SEPARATOR = "__"
SUPPORTED_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")


def runtime_key(entry, pass_environment):
    relevant = {k: v for k, v in (entry or {}).items() if k not in ("description", "disabledTools", "enabledTools")}
    return json.dumps([relevant, pass_environment], sort_keys=True)


def labelled(upstream, item):
    base = item.get("title") or (item.get("annotations") or {}).get("title") \
        or re.sub(r"(?<=[a-z0-9])(?=[A-Z])|[_-]+", " ", item["name"]).capitalize()
    title = f"{upstream.name}: {base}"
    result = {**item, "name": f"{upstream.prefix}{SEPARATOR}{item['name']}", "title": title}
    if (item.get("annotations") or {}).get("title"):
        result["annotations"] = {**item["annotations"], "title": title}
    return result


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
        self.prefix = re.sub(r"[^A-Za-z0-9_-]", "_", name)
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
        except AuthRequired as e:
            self.challenge = e.challenge
            self.error = "Sign-in required"
            self.state = "auth"
            self.close()
        except (RpcError, OSError) as e:
            stderr = [x["data"] for x in self.session.log if x["kind"] in ("stderr", "error")] if self.session else []
            self.error = str(e).splitlines()[0] + (f" – {stderr[-1]}" if stderr else "")
            self.state = "error"
            self.close()

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
                except RpcError:
                    self.catalog[key] = []

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

    def request(self, method, params):
        if not self.alive():
            raise RpcError(f"Server “{self.name}” is not running")
        try:
            return self.session.request(method, params, timeout=300)
        except AuthRequired:
            self.close()
            if not oauth.access_token(self.name, force_refresh=True):
                self.state, self.error = "auth", "Sign-in required"
                raise
            self.start(self.pass_environment)
            if self.state != "running":
                raise RpcError(f"Server “{self.name}”: {self.error}")
            return self.session.request(method, params, timeout=300)

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
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2))
            tmp.replace(self.path)

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
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.appended += 1
            if self.appended % 500 == 0:
                self.path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.entries))
            else:
                with self.path.open("a") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

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
                "name": (client_info or {}).get("name") or user_agent or "unbekannt",
                "version": (client_info or {}).get("version"),
                "since": now,
            }
            self.active[session_id] = {"profile": profile, "mode": mode, "lastSeen": now, "requests": 1, "calls": 0, "streams": 0}
            while len(self.sessions) > self.keep:
                self.sessions.pop(next(iter(self.sessions)))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.sessions))
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

    def sync(self):
        pass_environment = self.load_settings()["passEnvironment"]
        wanted = {
            name: entry for name, entry in self.load_config()["mcpServers"].items()
            if entry.get("enabled", True) and (entry.get("command") or entry.get("url"))
        }
        with self.lock:
            for name, upstream in list(self.upstreams.items()):
                key = runtime_key(wanted.get(name), pass_environment)
                crashed = upstream.state == "running" and not upstream.alive()
                if name not in wanted or upstream.key != key or crashed:
                    upstream.close()
                    del self.upstreams[name]
            starting = []
            for name, entry in wanted.items():
                if name in self.upstreams:
                    self.upstreams[name].entry = entry
                else:
                    upstream = Upstream(name, entry, runtime_key(entry, pass_environment), self.sync_in_background)
                    self.upstreams[name] = upstream
                    thread = threading.Thread(target=upstream.start, args=(pass_environment,), daemon=True)
                    thread.start()
                    starting.append(thread)
            for thread in starting:
                thread.join(150)
            for upstream in self.upstreams.values():
                if upstream.state == "running" and upstream.stale:
                    upstream.refresh()
            running = [u for u in self.upstreams.values() if u.state == "running"]
            self._notify_if_changed(running)
            return running

    def reconnect(self, name):
        with self.lock:
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
                **({"oauth": oauth.status(name)} if u.entry.get("url") else {}),
            }
            for name, u in self.upstreams.items()
        }

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
            return {u: set(u.entry.get("disabledTools") or []) for u in running}
        saved = self.load_profiles()["profiles"].get(profile)
        if saved is None:
            raise JsonRpcError(-32602, f"Unknown profile: {profile}")
        view = {}
        for upstream in running:
            wanted = saved["servers"].get(upstream.name)
            if wanted is None:
                view[upstream] = set(upstream.entry.get("disabledTools") or [])
            elif wanted["enabled"]:
                view[upstream] = set(wanted["disabledTools"])
        return view

    def _route(self, running, prefixed):
        for upstream in sorted(running, key=lambda u: -len(u.prefix)):
            if prefixed.startswith(upstream.prefix + SEPARATOR):
                return upstream, prefixed[len(upstream.prefix) + len(SEPARATOR):]
        raise JsonRpcError(-32602, f"Unknown: {prefixed}")

    def handle(self, method, params, client="unbekannt", profile=None, mode=None):
        params = params or {}
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

        view = self._view(self.sync(), profile)
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
