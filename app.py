#!/usr/bin/env python3
import atexit
import json
import os
import queue
import re
import shutil
import signal
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import hub as hub_module
import inspector
import secrets_store

ROOT = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("MCP_PROXY_GUI_HOME", Path.home() / ".config" / "mcp-proxy"))
SETTINGS_FILE = STATE_DIR / "gui-settings.json"
PROFILES_FILE = STATE_DIR / "profiles.json"

DEFAULT_SETTINGS = {
    "configPath": str(STATE_DIR / "servers.json"),
    "proxyBinary": shutil.which("mcp-proxy") or "mcp-proxy",
    "passEnvironment": True,
}


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def write_json(path, data):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def load_settings():
    stored = read_json(SETTINGS_FILE, {})
    return {k: stored.get(k, v) for k, v in DEFAULT_SETTINGS.items()}


def config_path():
    return Path(load_settings()["configPath"]).expanduser()


def load_config():
    data = read_json(config_path(), {"mcpServers": {}})
    data.setdefault("mcpServers", {})
    return data


def validate_servers(servers):
    if not isinstance(servers, dict):
        return "mcpServers muss ein Objekt sein"
    for name, entry in servers.items():
        if not name or "/" in name or name.strip() != name:
            return f"Ungültiger Name: {name!r}"
        if not isinstance(entry, dict):
            return f"{name}: Eintrag muss ein Objekt sein"
        if not entry.get("command") and not entry.get("url"):
            return f"{name}: command oder url fehlt"
        if not isinstance(entry.get("headers", {}), dict):
            return f"{name}: headers muss ein Objekt sein"
        if not isinstance(entry.get("args", []), list):
            return f"{name}: args muss eine Liste sein"
        if not isinstance(entry.get("disabledTools", []), list):
            return f"{name}: disabledTools muss eine Liste sein"
        if not isinstance(entry.get("env", {}), dict):
            return f"{name}: env muss ein Objekt sein"
    return None


def load_profiles():
    data = read_json(PROFILES_FILE, {})
    return {"active": data.get("active"), "profiles": data.get("profiles") or {}}


def profile_snapshot(servers):
    return {name: {"enabled": entry.get("enabled", True), "disabledTools": sorted(entry.get("disabledTools") or [])}
            for name, entry in servers.items()}


def update_profiles(action, name, new_name=None):
    data = load_profiles()
    profiles = data["profiles"]
    if action == "clear":
        data["active"] = None
    elif not name or not name.strip() or "/" in name:
        return "Profilname fehlt oder enthält „/“"
    elif action == "save":
        profiles[name] = {"servers": profile_snapshot(load_config()["mcpServers"])}
        data["active"] = name
    elif action == "apply":
        if name not in profiles:
            return f"Unbekanntes Profil: {name}"
        config = load_config()
        for server, wanted in profiles[name]["servers"].items():
            entry = config["mcpServers"].get(server)
            if entry is None:
                continue
            entry["enabled"] = wanted["enabled"]
            if wanted["disabledTools"]:
                entry["disabledTools"] = wanted["disabledTools"]
            else:
                entry.pop("disabledTools", None)
        write_json(config_path(), config)
        sync_hub_in_background()
        data["active"] = name
    elif action == "rename":
        new_name = (new_name or "").strip()
        if name not in profiles:
            return f"Unbekanntes Profil: {name}"
        if not new_name or "/" in new_name:
            return "Ungültiger neuer Name"
        if new_name != name and new_name in profiles:
            return f"Profil „{new_name}“ gibt es schon"
        profiles[new_name] = profiles.pop(name)
        if data["active"] == name:
            data["active"] = new_name
    elif action == "delete":
        profiles.pop(name, None)
        if data["active"] == name:
            data["active"] = None
    else:
        return f"Unbekannte Aktion: {action}"
    write_json(PROFILES_FILE, data)
    return None


hub = hub_module.Hub(load_config, load_settings, STATE_DIR, load_profiles)
MCP_PATH = re.compile(r"^/(?:p/([^/]+)/)?mcp$")


def sync_hub_in_background():
    threading.Thread(target=hub.sync, daemon=True).start()


def local_origin(origin):
    return not origin or urlparse(origin).hostname in ("localhost", "127.0.0.1", "::1")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send(self, payload, status=HTTPStatus.OK, content_type="application/json", headers=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def state(self):
        return {
            "configPath": str(config_path()),
            "config": load_config(),
            "settings": load_settings(),
            "profiles": load_profiles(),
        }

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self.send((ROOT / "index.html").read_bytes(), content_type="text/html; charset=utf-8")
        if self.path == "/api/state":
            return self.send(self.state())
        if self.path == "/api/hub":
            return self.send(hub.status())
        if self.path == "/api/usage":
            return self.send(hub.usage.snapshot())
        if self.path.startswith("/api/hub/tools"):
            tools = hub.tools(parse_qs(urlparse(self.path).query).get("name", [""])[0])
            if tools is None:
                return self.send({"error": "Server läuft nicht im Hub"}, HTTPStatus.NOT_FOUND)
            return self.send(tools)
        if self.path.startswith("/api/calls"):
            limit = int(parse_qs(urlparse(self.path).query).get("limit", ["300"])[0])
            return self.send(hub.calls.recent(min(limit, 1000)))
        if MCP_PATH.match(self.path):
            if "text/event-stream" not in self.headers.get("Accept", ""):
                self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
                self.send_header("Allow", "POST")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if not local_origin(self.headers.get("Origin")):
                return self.send({"error": "Origin nicht erlaubt"}, HTTPStatus.FORBIDDEN)
            return self.event_stream()
        url = urlparse(self.path)
        if url.path == "/api/inspect/log":
            query = parse_qs(url.query)
            return self.send(inspector.log(query.get("name", [""])[0], float(query.get("since", ["0"])[0])))
        self.send({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        if not local_origin(self.headers.get("Origin")):
            return self.send({"error": "Origin nicht erlaubt"}, HTTPStatus.FORBIDDEN)
        try:
            data = self.body()
        except json.JSONDecodeError as e:
            return self.send({"error": f"Ungültiges JSON: {e}"}, HTTPStatus.BAD_REQUEST)
        if self.path == "/api/servers":
            servers = data.get("mcpServers")
            if error := validate_servers(servers):
                return self.send({"error": error}, HTTPStatus.BAD_REQUEST)
            config = load_config()
            config["mcpServers"] = servers
            write_json(config_path(), config)
            sync_hub_in_background()
            return self.send(self.state())
        if self.path == "/api/settings":
            settings = {k: data.get(k, v) for k, v in load_settings().items()}
            write_json(SETTINGS_FILE, settings)
            sync_hub_in_background()
            return self.send(self.state())
        self.send({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if not local_origin(self.headers.get("Origin")):
            return self.send({"error": "Origin nicht erlaubt"}, HTTPStatus.FORBIDDEN)
        if match := MCP_PATH.match(self.path):
            return self.mcp(unquote(match.group(1)) if match.group(1) else None)
        if self.path == "/api/profiles":
            data = self.body()
            if error := update_profiles(data.get("action"), data.get("name"), data.get("newName")):
                return self.send({"error": error}, HTTPStatus.BAD_REQUEST)
            return self.send(self.state())
        if self.path == "/api/secrets":
            data = self.body()
            try:
                return self.send({"ref": secrets_store.store_keychain(data.get("name", ""), data.get("value", ""))})
            except secrets_store.SecretError as e:
                return self.send({"error": str(e)}, HTTPStatus.BAD_REQUEST)
        if self.path.startswith("/api/inspect/"):
            return self.inspect(self.path.removeprefix("/api/inspect/"))
        self.send({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def event_stream(self):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        listener = hub.subscribe()
        try:
            while True:
                try:
                    message = listener.get(timeout=25)
                    self.wfile.write(f"event: message\ndata: {json.dumps(message)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            hub.unsubscribe(listener)

    def mcp(self, profile=None):
        try:
            message = self.body()
        except json.JSONDecodeError:
            return self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                             HTTPStatus.BAD_REQUEST)
        if not isinstance(message, dict) or "method" not in message or "id" not in message:
            self.send_response(HTTPStatus.ACCEPTED)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        reply = {"jsonrpc": "2.0", "id": message["id"]}
        user_agent = self.headers.get("User-Agent", "")
        headers = {}
        if message["method"] == "initialize":
            client_info = (message.get("params") or {}).get("clientInfo")
            headers["Mcp-Session-Id"] = hub.clients.register(client_info, user_agent)
            client = hub.clients.lookup(headers["Mcp-Session-Id"], user_agent)
        else:
            client = hub.clients.lookup(self.headers.get("Mcp-Session-Id"), user_agent)
        if profile:
            client = f"{client} · {profile}"
        try:
            reply["result"] = hub.handle(message["method"], message.get("params"), client, profile)
        except hub_module.JsonRpcError as e:
            reply["error"] = {"code": e.code, "message": str(e)}
        except Exception as e:
            reply["error"] = {"code": -32603, "message": f"Interner Fehler: {e}"}
        self.send(reply, headers=headers)

    def do_DELETE(self):
        if MCP_PATH.match(self.path):
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        self.send({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def inspect(self, action):
        data = self.body()
        name = data.get("name", "")
        try:
            if action == "connect":
                entry = load_config()["mcpServers"].get(name)
                if not entry:
                    return self.send({"error": f"Unbekannter Server: {name}"}, HTTPStatus.NOT_FOUND)
                return self.send(inspector.connect(name, entry, load_settings()["passEnvironment"]))
            if action == "call":
                return self.send({"result": inspector.call(name, data["method"], data.get("params"))})
            if action == "disconnect":
                inspector.disconnect(name)
                return self.send({})
        except inspector.RpcError as e:
            return self.send({"error": str(e)}, HTTPStatus.BAD_GATEWAY)
        except OSError as e:
            return self.send({"error": f"Start fehlgeschlagen: {e}"}, HTTPStatus.BAD_GATEWAY)
        self.send({"error": "not found"}, HTTPStatus.NOT_FOUND)


def main():
    port = int(os.environ.get("PORT", 4747))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    atexit.register(inspector.disconnect_all)
    atexit.register(hub.close)
    sync_hub_in_background()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print(f"MCP Hub läuft auf http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
