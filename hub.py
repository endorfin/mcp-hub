import json
import re
import threading
import uuid
from collections import deque
import time
from pathlib import Path

from inspector import PROTOCOL_VERSION, RpcError, open_session

SEPARATOR = "__"
SUPPORTED_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")


def runtime_key(entry, pass_environment):
    relevant = {k: v for k, v in (entry or {}).items() if k != "description"}
    return json.dumps([relevant, pass_environment], sort_keys=True)


def labelled(upstream, item):
    base = item.get("title") or (item.get("annotations") or {}).get("title") \
        or re.sub(r"(?<=[a-z0-9])(?=[A-Z])|[_-]+", " ", item["name"]).capitalize()
    title = f"{upstream.name}: {base}"
    result = {**item, "name": f"{upstream.prefix}{SEPARATOR}{item['name']}", "title": title}
    if (item.get("annotations") or {}).get("title"):
        result["annotations"] = {**item["annotations"], "title": title}
    return result


class JsonRpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Upstream:
    def __init__(self, name, entry, key):
        self.name = name
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

    def start(self, pass_environment):
        try:
            self.session = open_session(self.name, self.entry, pass_environment, "mcp-hub")
            self.session.on_notification = self._on_notification
            info = self.session.initialize()
            self.capabilities = info.get("capabilities", {})
            self.server_info = info.get("serverInfo") or {}
            self.instructions = info.get("instructions") or ""
            self.refresh()
            self.state = "running"
        except (RpcError, OSError) as e:
            stderr = [x["data"] for x in self.session.log if x["kind"] in ("stderr", "error")] if self.session else []
            self.error = str(e).splitlines()[0] + (f" – {stderr[-1]}" if stderr else "")
            self.state = "error"
            self.close()

    def _on_notification(self, message):
        if message["method"].endswith("/list_changed"):
            self.stale = True

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

    def alive(self):
        return self.session is not None and self.session.alive()

    def request(self, method, params):
        if not self.alive():
            raise RpcError(f"Server „{self.name}“ läuft nicht")
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
    def __init__(self, path, keep=1000):
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


class Clients:
    def __init__(self, path, keep=300):
        self.path = Path(path)
        self.keep = keep
        self.lock = threading.Lock()
        try:
            self.sessions = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self.sessions = {}

    def register(self, client_info, user_agent):
        session_id = uuid.uuid4().hex
        with self.lock:
            self.sessions[session_id] = {
                "name": (client_info or {}).get("name") or user_agent or "unbekannt",
                "version": (client_info or {}).get("version"),
                "since": time.time(),
            }
            while len(self.sessions) > self.keep:
                self.sessions.pop(next(iter(self.sessions)))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.sessions))
        return session_id

    def lookup(self, session_id, user_agent):
        session = self.sessions.get(session_id or "")
        if session:
            return session["name"]
        return f"{user_agent.split('/')[0]} (ohne Sitzung)" if user_agent else "unbekannt"


def preview(value, limit):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + " …"


def first_text(result):
    for block in (result or {}).get("content") or (result or {}).get("contents") or []:
        if block.get("text"):
            return block["text"]
    return ""


class Hub:
    def __init__(self, load_config, load_settings, state_dir):
        self.load_config = load_config
        self.load_settings = load_settings
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
                if name not in self.upstreams:
                    upstream = Upstream(name, entry, runtime_key(entry, pass_environment))
                    self.upstreams[name] = upstream
                    thread = threading.Thread(target=upstream.start, args=(pass_environment,), daemon=True)
                    thread.start()
                    starting.append(thread)
            for thread in starting:
                thread.join(150)
            for upstream in self.upstreams.values():
                if upstream.state == "running" and upstream.stale:
                    upstream.refresh()
            return [u for u in self.upstreams.values() if u.state == "running"]

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
                "summary": u.server_info.get("description") or u.instructions.strip().split("\n")[0][:300]
                or ", ".join(t["name"] for t in u.catalog["tools"][:6]) + (" …" if len(u.catalog["tools"]) > 6 else ""),
                **{k: len(v) for k, v in u.catalog.items()},
            }
            for name, u in self.upstreams.items()
        }

    def _route(self, running, prefixed):
        for upstream in sorted(running, key=lambda u: -len(u.prefix)):
            if prefixed.startswith(upstream.prefix + SEPARATOR):
                return upstream, prefixed[len(upstream.prefix) + len(SEPARATOR):]
        raise JsonRpcError(-32602, f"Unbekannt: {prefixed}")

    def handle(self, method, params, client="unbekannt"):
        params = params or {}
        if method == "initialize":
            requested = params.get("protocolVersion")
            return {
                "protocolVersion": requested if requested in SUPPORTED_VERSIONS else PROTOCOL_VERSION,
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}, "logging": {}},
                "serverInfo": {"name": "mcp-hub", "version": "1.0"},
                "instructions": "Bündelt mehrere MCP-Server. Tool- und Prompt-Namen tragen den Servernamen als Präfix (server__tool).",
            }
        if method in ("ping", "logging/setLevel"):
            return {}

        running = self.sync()
        if method == "tools/list":
            return {"tools": [labelled(u, t) for u in running for t in u.catalog["tools"]]}
        if method == "prompts/list":
            return {"prompts": [labelled(u, p) for u in running for p in u.catalog["prompts"]]}
        if method == "resources/list":
            return {"resources": [r for u in running for r in u.catalog["resources"]]}
        if method == "resources/templates/list":
            return {"resourceTemplates": [t for u in running for t in u.catalog["resourceTemplates"]]}
        if method == "tools/call":
            upstream, name = self._route(running, params.get("name", ""))
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
            raise JsonRpcError(-32002, f"Resource nicht gefunden: {uri}")
        raise JsonRpcError(-32601, f"Methode nicht unterstützt: {method}")

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
