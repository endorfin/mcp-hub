import json
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from urllib.parse import urljoin

import oauth
from secrets_store import SecretError, resolve_entry

PROTOCOL_VERSION = "2025-06-18"
VERSION = "0.3.0"
DEFAULT_ENV_KEYS = ("HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER", "LANG", "TMPDIR")
USER_AGENT = "mcp-hub/1.0"


class RpcError(Exception):
    pass


class AuthRequired(RpcError):
    def __init__(self, challenge=""):
        super().__init__("Sign-in required (HTTP 401)")
        self.challenge = challenge


class BaseSession:
    def __init__(self, name, client_name):
        self.name = name
        self.client_name = client_name
        self.log = deque(maxlen=500)
        self.pending = {}
        self.next_id = 1
        self.lock = threading.Lock()
        self.initialize_result = None
        self.on_notification = None

    def _record(self, kind, payload):
        self.log.append({"t": time.time(), "kind": kind, "data": payload})

    def _send(self, message):
        raise NotImplementedError

    def alive(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def _dispatch(self, message):
        if isinstance(message, list):
            for item in message:
                self._dispatch(item)
            return
        if "method" in message and "id" in message:
            self._answer_server_request(message)
        elif "method" in message:
            self._record("notification", message)
            if self.on_notification:
                self.on_notification(message)
        elif message.get("id") in self.pending:
            slot = self.pending[message["id"]]
            slot["response"] = message
            slot["event"].set()

    def _release_pending(self):
        for slot in list(self.pending.values()):
            slot["event"].set()

    def _answer_server_request(self, message):
        self._record("server-request", message)
        if message["method"] == "ping":
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": {}}
        elif message["method"] == "roots/list":
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": {"roots": []}}
        else:
            reply = {"jsonrpc": "2.0", "id": message["id"],
                     "error": {"code": -32601, "message": "Not supported by the hub"}}
        try:
            self._send(reply)
        except (RpcError, OSError) as e:
            self._record("error", f"Reply to server failed: {e}")

    def request(self, method, params=None, timeout=60):
        with self.lock:
            request_id = self.next_id
            self.next_id += 1
        slot = {"event": threading.Event(), "response": None}
        self.pending[request_id] = slot
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        try:
            self._send(message)
        except RpcError:
            self.pending.pop(request_id, None)
            raise
        except OSError as e:
            self.pending.pop(request_id, None)
            raise RpcError(f"Connection failed: {e}")
        finished = slot["event"].wait(timeout)
        self.pending.pop(request_id, None)
        if not finished:
            raise RpcError(f"No response to {method} after {timeout} s")
        response = slot["response"]
        if response is None:
            raise RpcError("Connection to the server was closed")
        if "error" in response:
            error = response["error"]
            raise RpcError(f"{error.get('message')} (Code {error.get('code')})")
        return response.get("result")

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def initialize(self):
        self.initialize_result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"roots": {"listChanged": False}},
            "clientInfo": {"name": self.client_name, "version": VERSION},
        }, timeout=120)
        self.notify("notifications/initialized")
        return self.initialize_result

    def list_all(self, method, key):
        items, cursor = [], None
        while True:
            result = self.request(method, {"cursor": cursor} if cursor else {})
            items += result.get(key, [])
            cursor = result.get("nextCursor")
            if not cursor:
                return items


class StdioSession(BaseSession):
    def __init__(self, name, entry, pass_environment, client_name):
        super().__init__(name, client_name)
        env = {k: os.environ[k] for k in DEFAULT_ENV_KEYS if k in os.environ}
        if pass_environment:
            env.update(os.environ)
        env.update(entry.get("env") or {})
        self.proc = subprocess.Popen(
            [entry["command"], *entry.get("args", [])],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=os.path.expanduser(entry["cwd"]) if entry.get("cwd") else None,
            start_new_session=True,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _send(self, message):
        try:
            self.proc.stdin.write((json.dumps(message) + "\n").encode())
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise RpcError("Server process is no longer running")

    def _read_stderr(self):
        for line in self.proc.stderr:
            self._record("stderr", line.decode(errors="replace").rstrip())

    def _read_stdout(self):
        for line in self.proc.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._record("stdout", line.decode(errors="replace").rstrip())
                continue
            self._dispatch(message)
        self._record("exit", f"Process exited (code {self.proc.wait()})")
        self._release_pending()

    def alive(self):
        return self.proc.poll() is None

    def close(self):
        if self.alive():
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(3)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def read_events(response):
    event, data = "message", []
    for raw in response:
        line = raw.decode(errors="replace").rstrip("\r\n")
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield event, "\n".join(data)


def http_error(e):
    try:
        body = e.read().decode(errors="replace").strip()
    except OSError:
        body = ""
    return RpcError(f"HTTP {e.code} {e.reason}" + (f": {body[:300]}" if body else ""))


class HttpSession(BaseSession):
    def __init__(self, name, entry, client_name):
        super().__init__(name, client_name)
        self.url = entry["url"]
        self.headers = entry.get("headers") or {}
        self.session_id = None
        self.protocol_version = None
        self.closed = False

    def _headers(self):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": USER_AGENT,
            **self.headers,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        return headers

    def _send(self, message):
        if self.closed:
            raise RpcError("Connection is closed")
        request = urllib.request.Request(self.url, json.dumps(message).encode(), self._headers(), method="POST")
        try:
            response = urllib.request.urlopen(request, timeout=300)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                with e:
                    raise AuthRequired(e.headers.get("WWW-Authenticate", ""))
            raise http_error(e)
        self.session_id = response.headers.get("Mcp-Session-Id") or self.session_id
        content_type = response.headers.get("Content-Type", "")
        if content_type.startswith("text/event-stream"):
            threading.Thread(target=self._read_stream, args=(response,), daemon=True).start()
            return
        body = response.read()
        response.close()
        if body.strip():
            try:
                self._dispatch(json.loads(body))
            except json.JSONDecodeError:
                self._record("stdout", body.decode(errors="replace")[:500])

    def _read_stream(self, response):
        try:
            for _, data in read_events(response):
                try:
                    self._dispatch(json.loads(data))
                except json.JSONDecodeError:
                    self._record("stdout", data[:500])
        except OSError as e:
            self._record("error", f"Stream aborted: {e}")
        finally:
            response.close()

    def initialize(self):
        result = super().initialize()
        self.protocol_version = result.get("protocolVersion")
        return result

    def alive(self):
        return not self.closed

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.session_id:
            request = urllib.request.Request(self.url, headers=self._headers(), method="DELETE")
            try:
                urllib.request.urlopen(request, timeout=5).close()
            except OSError:
                pass
        self._release_pending()


class SseSession(BaseSession):
    def __init__(self, name, entry, client_name):
        super().__init__(name, client_name)
        self.url = entry["url"]
        self.headers = entry.get("headers") or {}
        self.endpoint = None
        self.endpoint_ready = threading.Event()
        self.closed = False
        self.stream = None
        self.auth_challenge = None
        threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self):
        request = urllib.request.Request(self.url, headers={
            "Accept": "text/event-stream", "User-Agent": USER_AGENT, **self.headers})
        try:
            self.stream = urllib.request.urlopen(request, timeout=600)
            for event, data in read_events(self.stream):
                if event == "endpoint":
                    self.endpoint = urljoin(self.url, data)
                    self.endpoint_ready.set()
                    continue
                try:
                    self._dispatch(json.loads(data))
                except json.JSONDecodeError:
                    self._record("stdout", data[:500])
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.auth_challenge = e.headers.get("WWW-Authenticate", "")
            self._record("error", str(http_error(e)))
        except OSError as e:
            if not self.closed:
                self._record("error", f"SSE connection aborted: {e}")
        finally:
            self.closed = True
            self.endpoint_ready.set()
            self._release_pending()
            self._record("exit", "SSE connection closed")

    def _send(self, message):
        if not self.endpoint_ready.wait(30) or not self.endpoint:
            if self.auth_challenge is not None:
                raise AuthRequired(self.auth_challenge)
            errors = [x["data"] for x in self.log if x["kind"] == "error"]
            raise RpcError(errors[-1] if errors else "No endpoint received from the SSE server")
        if self.closed:
            raise RpcError("SSE connection is closed")
        request = urllib.request.Request(self.endpoint, json.dumps(message).encode(), {
            "Content-Type": "application/json", "User-Agent": USER_AGENT, **self.headers}, method="POST")
        try:
            urllib.request.urlopen(request, timeout=60).close()
        except urllib.error.HTTPError as e:
            raise http_error(e)

    def alive(self):
        return not self.closed

    def close(self):
        self.closed = True
        # response.close() blockiert, solange _listen noch liest; shutdown weckt den Leser auf.
        sock = getattr(getattr(getattr(self.stream, "fp", None), "raw", None), "_sock", None)
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def transport(entry):
    kind = (entry.get("type") or "").lower()
    if kind == "sse":
        return "sse"
    if kind in ("http", "streamable-http", "streamablehttp") or (entry.get("url") and not entry.get("command")):
        return "http"
    return "stdio"


def open_session(name, entry, pass_environment, client_name):
    try:
        entry = resolve_entry(entry)
    except SecretError as e:
        raise RpcError(f"Secret: {e}")
    kind = transport(entry)
    headers = entry.get("headers") or {}
    if kind != "stdio" and not any(k.lower() == "authorization" for k in headers):
        token = oauth.access_token(name)
        if token:
            entry = {**entry, "headers": {**headers, "Authorization": f"Bearer {token}"}}
    if kind == "http":
        return HttpSession(name, entry, client_name)
    if kind == "sse":
        return SseSession(name, entry, client_name)
    return StdioSession(name, entry, pass_environment, client_name)


sessions = {}


def connect(name, entry, pass_environment):
    disconnect(name)
    session = open_session(name, entry, pass_environment, "mcp-hub-inspector")
    sessions[name] = session
    try:
        info = session.initialize()
    except RpcError as e:
        raise RpcError(f"{e}\n\n" + "\n".join(
            str(x["data"]) for x in session.log if x["kind"] in ("stderr", "stdout", "exit", "error"))[-4000:])
    capabilities = info.get("capabilities", {})
    catalog = {"tools": [], "resources": [], "resourceTemplates": [], "prompts": []}
    if "tools" in capabilities:
        catalog["tools"] = session.list_all("tools/list", "tools")
    if "resources" in capabilities:
        catalog["resources"] = session.list_all("resources/list", "resources")
        try:
            catalog["resourceTemplates"] = session.list_all("resources/templates/list", "resourceTemplates")
        except RpcError:
            pass
    if "prompts" in capabilities:
        catalog["prompts"] = session.list_all("prompts/list", "prompts")
    return {"initialize": info, **catalog}


def call(name, method, params):
    session = sessions.get(name)
    if not session or not session.alive():
        raise RpcError("Nicht verbunden")
    return session.request(method, params, timeout=300)


def disconnect(name):
    session = sessions.pop(name, None)
    if session:
        session.close()


def disconnect_all():
    for name in list(sessions):
        disconnect(name)


def log(name, since=0):
    session = sessions.get(name)
    if not session:
        return {"connected": False, "entries": []}
    return {
        "connected": session.alive(),
        "entries": [x for x in session.log if x["t"] > since],
    }
