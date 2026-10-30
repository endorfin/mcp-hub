#!/usr/bin/env python3
import atexit
import html
import json
import os
import queue
import re
import shutil
import signal
import socketserver
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import hub as hub_module
import importer
import integrations
import inspector
import oauth
import secrets_store
import updater as updater_module
from fsutil import atomic_write

ROOT = Path(__file__).resolve().parent
DEFAULT_HOME = Path(os.environ["APPDATA"]) / "mcp-hub" if sys.platform == "win32" and os.environ.get("APPDATA") \
    else Path.home() / ".config" / "mcp-hub"
STATE_DIR = Path(os.environ.get("MCP_HUB_HOME") or DEFAULT_HOME)
SETTINGS_FILE = STATE_DIR / "gui-settings.json"
PROFILES_FILE = STATE_DIR / "profiles.json"

DEFAULT_SETTINGS = {
    "configPath": str(STATE_DIR / "servers.json"),
    "passEnvironment": True,
    "language": "auto",
    "checkUpdates": True,
}
CALLBACK_TEXT = {
    "en": {"ok": "Signed in", "fail": "Sign-in failed", "connected": "“{server}” is connected.", "back": "Back to MCP Hub"},
    "de": {"ok": "Angemeldet", "fail": "Anmeldung fehlgeschlagen", "connected": "„{server}“ ist verbunden.", "back": "Zurück zum MCP Hub"},
}


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def write_json(path, data):
    path = Path(path).expanduser()
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


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
        return "mcpServers must be an object"
    for name, entry in servers.items():
        if not name or "/" in name or name.strip() != name:
            return f"Invalid name: {name!r}"
        if not isinstance(entry, dict):
            return f"{name}: entry must be an object"
        if not entry.get("command") and not entry.get("url"):
            return f"{name}: command or url is missing"
        if not isinstance(entry.get("headers", {}), dict):
            return f"{name}: headers must be an object"
        if not isinstance(entry.get("args", []), list):
            return f"{name}: args must be a list"
        if not isinstance(entry.get("oauth", {}), dict):
            return f"{name}: oauth must be an object"
        if not isinstance(entry.get("cwd", ""), str):
            return f"{name}: cwd must be a string"
        if not isinstance(entry.get("enabledTools", []), list):
            return f"{name}: enabledTools must be a list"
        if not isinstance(entry.get("disabledTools", []), list):
            return f"{name}: disabledTools must be a list"
        if not isinstance(entry.get("env", {}), dict):
            return f"{name}: env must be an object"
        for key in ("args", "env", "headers"):
            values = entry.get(key) or ([] if key == "args" else {})
            if not all(isinstance(v, str) for v in (values if key == "args" else values.values())):
                return f"{name}: values in {key} must be strings"
    prefixes = {}
    for name in servers:
        prefix = hub_module.prefix_of(name)
        if prefix in prefixes:
            return f"{prefixes[prefix]} and {name} would share the tool prefix {prefix}"
        prefixes[prefix] = name
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
        config = load_config()
        for entry in config["mcpServers"].values():
            entry["enabled"] = True
            entry.pop("disabledTools", None)
        write_json(config_path(), config)
        sync_hub_in_background()
        data["active"] = None
    elif not name or not name.strip() or "/" in name:
        return "Profile name is missing or contains “/”"
    elif action == "save":
        profiles[name] = {"servers": profile_snapshot(load_config()["mcpServers"])}
        data["active"] = name
    elif action == "apply":
        if name not in profiles:
            return f"Unknown profile: {name}"
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
            return f"Unknown profile: {name}"
        if not new_name or "/" in new_name:
            return "Invalid new name"
        if new_name != name and new_name in profiles:
            return f"Profile “{new_name}” already exists"
        profiles[new_name] = profiles.pop(name)
        if data["active"] == name:
            data["active"] = new_name
    elif action == "delete":
        profiles.pop(name, None)
        if data["active"] == name:
            data["active"] = None
    else:
        return f"Unknown action: {action}"
    write_json(PROFILES_FILE, data)
    return None


hub = hub_module.Hub(load_config, load_settings, STATE_DIR, load_profiles)
MCP_PATH = re.compile(r"^/(?:p/([^/]+)/)?mcp(?:/(compact))?$")


updater = updater_module.Updater(ROOT, STATE_DIR, inspector.VERSION)


def sync_hub_in_background():
    threading.Thread(target=hub.sync, daemon=True).start()


def bridge_info():
    python = sys.executable if sys.platform == "win32" else shutil.which("python3") or sys.executable
    return {"python": python, "script": str(ROOT / "bridge.py")}


def restart():
    time.sleep(0.5)
    inspector.disconnect_all()
    hub.close()
    sys.stdout.flush()
    os.execv(sys.executable, [sys.executable, *sys.argv])



class Server(ThreadingHTTPServer):
    # SO_REUSEADDR on Windows lets a second hub bind a port that is already in use.
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self):
        # HTTPServer.server_bind resolves the host name via getfqdn, which stalls for ~30 s on some macOS setups.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


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

    def query(self, name, default, cast=str):
        try:
            return cast(parse_qs(urlparse(self.path).query).get(name, [default])[0])
        except ValueError:
            return cast(default)

    def rejected(self, write=False):
        port = self.server.server_address[1]
        hosts = (f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}")
        if self.headers.get("Host") not in hosts:
            return HTTPStatus.FORBIDDEN, "Host not allowed"
        origin = self.headers.get("Origin")
        if origin and origin not in tuple(f"http://{host}" for host in hosts):
            return HTTPStatus.FORBIDDEN, "Origin not allowed"
        if write and self.path.startswith("/api/") and self.headers.get_content_type() != "application/json":
            return HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Content-Type must be application/json"
        return None

    def do_GET(self):
        if rejection := self.rejected():
            return self.send({"error": rejection[1]}, rejection[0])
        return self.get()

    def do_PUT(self):
        if rejection := self.rejected(write=True):
            return self.send({"error": rejection[1]}, rejection[0])
        try:
            return self.put()
        except json.JSONDecodeError as e:
            return self.send({"error": f"Invalid JSON: {e}"}, HTTPStatus.BAD_REQUEST)

    def do_POST(self):
        if rejection := self.rejected(write=True):
            return self.send({"error": rejection[1]}, rejection[0])
        try:
            return self.post()
        except json.JSONDecodeError as e:
            return self.send({"error": f"Invalid JSON: {e}"}, HTTPStatus.BAD_REQUEST)

    def do_DELETE(self):
        if rejection := self.rejected():
            return self.send({"error": rejection[1]}, rejection[0])
        return self.delete()

    def state(self):
        return {
            "version": inspector.VERSION,
            "configPath": str(config_path()),
            "config": load_config(),
            "settings": load_settings(),
            "profiles": load_profiles(),
            "bridge": bridge_info(),
        }

    def get(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            return self.send((ROOT / "index.html").read_bytes(), content_type="text/html; charset=utf-8")
        if self.path == "/api/state":
            return self.send(self.state())
        if self.path == "/api/hub":
            return self.send(hub.status())
        if self.path == "/api/live":
            return self.send(hub.live_clients())
        if self.path == "/api/clients":
            return self.send(hub.clients.snapshot())
        if self.path == "/api/integrations":
            return self.send(integrations.status(self.server.server_address[1]))
        if self.path == "/api/compact":
            full = json.dumps(hub.handle("tools/list", {})["tools"], ensure_ascii=False)
            small = json.dumps(hub.handle("tools/list", {}, mode="compact")["tools"], ensure_ascii=False)
            return self.send({"fullChars": len(full), "compactChars": len(small)})
        if self.path == "/api/update":
            enabled = load_settings()["checkUpdates"]
            if enabled and updater.stale():
                updater.check_in_background()
            return self.send({**updater.status(), "enabled": enabled})
        if self.path == "/api/usage":
            return self.send(hub.usage.snapshot())
        if self.path.startswith("/api/hub/tools"):
            tools = hub.tools(parse_qs(urlparse(self.path).query).get("name", [""])[0])
            if tools is None:
                return self.send({"error": "Server is not running in the hub"}, HTTPStatus.NOT_FOUND)
            return self.send(tools)
        if self.path.startswith("/api/stats"):
            days = self.query("days", "14", int)
            return self.send(hub.calls.stats(max(1, min(days, 90))))
        if self.path.startswith("/api/calls"):
            limit = self.query("limit", "300", int)
            return self.send(hub.calls.recent(min(limit, 1000)))
        if match := MCP_PATH.match(self.path):
            if "text/event-stream" not in self.headers.get("Accept", ""):
                self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
                self.send_header("Allow", "POST")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if not hub.clients.valid(self.headers.get("Mcp-Session-Id")):
                return self.send({"error": "Unknown session"}, HTTPStatus.NOT_FOUND)
            return self.event_stream(unquote(match.group(1)) if match.group(1) else None)
        url = urlparse(self.path)
        if url.path == "/oauth/callback":
            return self.oauth_callback(parse_qs(url.query))
        if url.path == "/api/inspect/log":
            return self.send(inspector.log(self.query("name", ""), self.query("since", "0", float)))
        self.send({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def put(self):
        data = self.body()
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

    def post(self):
        if match := MCP_PATH.match(self.path):
            return self.mcp(unquote(match.group(1)) if match.group(1) else None, match.group(2))
        if self.path.startswith("/api/integrations/"):
            data, port = self.body(), self.server.server_address[1]
            action = self.path.removeprefix("/api/integrations/")
            try:
                if action == "connect":
                    url = f"http://127.0.0.1:{port}/mcp" + ("/compact" if data.get("compact") else "")
                    integrations.connect(data.get("id", ""), url, port, bridge_info())
                elif action == "disconnect":
                    integrations.disconnect(data.get("id", ""), port)
                elif action == "remove":
                    integrations.remove(data.get("id", ""), data.get("names") or [])
                elif action == "export":
                    return self.send(integrations.export(data.get("id", ""), port))
                else:
                    return self.send({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except integrations.IntegrationError as e:
                return self.send({"error": str(e)}, HTTPStatus.CONFLICT)
            except OSError as e:
                return self.send({"error": f"Could not write the client configuration: {e}"}, HTTPStatus.CONFLICT)
            return self.send(integrations.status(port))
        if self.path == "/api/hub/restart":
            name = self.body().get("name", "")
            if name not in hub.upstreams:
                return self.send({"error": f"Unknown server: {name}"}, HTTPStatus.NOT_FOUND)
            hub.reconnect(name)
            return self.send({})
        if self.path == "/api/update/check":
            return self.send({**updater.check(), "enabled": load_settings()["checkUpdates"]})
        if self.path == "/api/update/apply":
            if updater.applying:
                return self.send({"error": "An update is already running"}, HTTPStatus.CONFLICT)
            try:
                version = updater.apply()
            except updater_module.UpdateError as e:
                return self.send({"error": str(e)}, HTTPStatus.CONFLICT)
            threading.Thread(target=restart, daemon=True).start()
            return self.send({"ok": True, "version": version})
        if self.path == "/api/profiles":
            data = self.body()
            if error := update_profiles(data.get("action"), data.get("name"), data.get("newName")):
                return self.send({"error": error}, HTTPStatus.BAD_REQUEST)
            return self.send(self.state())
        if self.path in ("/api/oauth/start", "/api/oauth/logout"):
            name = self.body().get("name", "")
            entry = load_config()["mcpServers"].get(name)
            if not entry or not entry.get("url"):
                return self.send({"error": f"Not a remote server: {name}"}, HTTPStatus.NOT_FOUND)
            if self.path.endswith("logout"):
                oauth.logout(name)
                hub.reconnect(name)
                return self.send({})
            try:
                settings = {k: secrets_store.resolve_value(v) for k, v in (entry.get("oauth") or {}).items()}
                url = oauth.start(name, secrets_store.resolve_value(entry["url"]), self.redirect_uri(), hub.challenge(name), settings)
            except (oauth.OAuthError, secrets_store.SecretError) as e:
                return self.send({"error": str(e)}, HTTPStatus.BAD_GATEWAY)
            return self.send({"url": url})
        if self.path == "/api/import/parse":
            try:
                result = importer.parse(self.body().get("text", ""), self.server.server_address[1])
            except importer.ImportError_ as e:
                return self.send({"error": str(e)}, HTTPStatus.BAD_REQUEST)
            result["existing"] = sorted(set(result["servers"]) & set(load_config()["mcpServers"]))
            return self.send(result)
        if self.path == "/api/secrets":
            data = self.body()
            try:
                return self.send({"ref": secrets_store.store_keychain(data.get("name", ""), data.get("value", ""))})
            except secrets_store.SecretError as e:
                return self.send({"error": str(e)}, HTTPStatus.BAD_REQUEST)
        if self.path.startswith("/api/inspect/"):
            return self.inspect(self.path.removeprefix("/api/inspect/"))
        self.send({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def redirect_uri(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}/oauth/callback"

    def oauth_callback(self, query):
        error = query.get("error_description", query.get("error", [""]))[0]
        server = None
        if not error:
            try:
                server = oauth.finish(query.get("state", [""])[0], query.get("code", [""])[0])
                hub.reconnect(server)
            except (oauth.OAuthError, secrets_store.SecretError) as e:
                error = str(e)
        language = load_settings()["language"]
        if language not in CALLBACK_TEXT:
            language = "de" if self.headers.get("Accept-Language", "").lower().startswith("de") else "en"
        words = CALLBACK_TEXT[language]
        title = words["fail"] if error else words["ok"]
        text = error or words["connected"].format(server=server)
        message = json.dumps({"type": "mcp-hub-oauth", "server": server, "error": error or None}).replace("<", "\\u003c")
        page = f"""<!doctype html><html lang="{language}"><meta charset="utf-8"><title>{title} · MCP Hub</title>
<style>:root{{--bg:#f6f6f4;--ink:#1c1c1a;--muted:#6b6b66;--tone:{"#c0362c" if error else "#1f8a4c"}}}@media (prefers-color-scheme:dark){{:root{{--bg:#141413;--ink:#ecebe6;--muted:#9a998f;--tone:{"#ff7366" if error else "#4cc27f"}}}}}body{{margin:0;min-height:100vh;display:grid;place-items:center;font:14px/1.45 -apple-system,system-ui,sans-serif;background:var(--bg);color:var(--ink)}}main{{max-width:420px;padding:24px;text-align:center;display:grid;gap:14px}}h1{{font-size:16px;margin:0;color:var(--tone)}}p{{margin:0;color:var(--muted)}}a{{color:var(--ink);text-underline-offset:3px}}</style>
<main><h1>{title}</h1><p>{html.escape(text)}</p><a href="/">{words["back"]}</a></main>
<script>if (window.opener) {{ window.opener.postMessage({message}, location.origin); {"" if error else "setTimeout(() => window.close(), 1200);"} }}</script></html>"""
        self.send(page.encode(), HTTPStatus.BAD_REQUEST if error else HTTPStatus.OK, "text/html; charset=utf-8")

    def event_stream(self, profile=None):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        session_id = self.headers.get("Mcp-Session-Id")
        client = hub.clients.lookup(session_id, self.headers.get("User-Agent", ""))
        listener = hub.subscribe(f"{client} · {profile}" if profile else client)
        hub.clients.stream(session_id, 1)
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
            hub.clients.stream(session_id, -1)

    def mcp(self, profile=None, mode=None):
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
        if message["method"] != "initialize" and not hub.clients.valid(self.headers.get("Mcp-Session-Id")):
            return self.send({"jsonrpc": "2.0", "id": message["id"],
                              "error": {"code": -32001, "message": "Unknown session, please initialize again"}},
                             HTTPStatus.NOT_FOUND)
        if message["method"] == "initialize":
            client_info = (message.get("params") or {}).get("clientInfo")
            headers["Mcp-Session-Id"] = hub.clients.register(client_info, user_agent, profile, mode)
            client = hub.clients.lookup(headers["Mcp-Session-Id"], user_agent)
        else:
            session_id = self.headers.get("Mcp-Session-Id")
            hub.clients.touch(session_id, message["method"] in ("tools/call", "prompts/get", "resources/read"))
            client = hub.clients.lookup(session_id, user_agent)
        if profile:
            client = f"{client} · {profile}"
        try:
            reply["result"] = hub.handle(message["method"], message.get("params"), client, profile, mode)
        except hub_module.JsonRpcError as e:
            reply["error"] = {"code": e.code, "message": str(e)}
        except Exception as e:
            reply["error"] = {"code": -32603, "message": f"Internal error: {e}"}
        self.send(reply, headers=headers)

    def delete(self):
        if MCP_PATH.match(self.path):
            hub.clients.end(self.headers.get("Mcp-Session-Id"))
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
                    return self.send({"error": f"Unknown server: {name}"}, HTTPStatus.NOT_FOUND)
                return self.send(inspector.connect(name, entry, load_settings()["passEnvironment"]))
            if action == "call":
                return self.send({"result": inspector.call(name, data["method"], data.get("params"))})
            if action == "disconnect":
                inspector.disconnect(name)
                return self.send({})
        except inspector.RpcError as e:
            return self.send({"error": str(e)}, HTTPStatus.BAD_GATEWAY)
        except OSError as e:
            return self.send({"error": f"Start failed: {e}"}, HTTPStatus.BAD_GATEWAY)
        self.send({"error": "not found"}, HTTPStatus.NOT_FOUND)


def option(name, default=None):
    if name in sys.argv[1:-1]:
        return sys.argv[sys.argv.index(name) + 1]
    return default


def bind(port, attempts=20):
    for attempt in range(attempts):
        try:
            return Server(("127.0.0.1", port), Handler)
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5)


def main():
    if log := option("--log"):
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(log, "a", buffering=1, encoding="utf-8")
    port = int(option("--port", os.environ.get("PORT", 4747)))
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    server = bind(port)
    atexit.register(inspector.disconnect_all)
    atexit.register(hub.close)
    sync_hub_in_background()
    hub.supervise_in_background()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print(f"MCP Hub running at http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
