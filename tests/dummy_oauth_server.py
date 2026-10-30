import base64
import hashlib
import json
import secrets
import socketserver
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

PORT = int(sys.argv[1])
FIXED = "--fixed-client" in sys.argv
BASE = f"http://127.0.0.1:{PORT}"
FIXED_ID, FIXED_SECRET = "fixed-id", "fixed-secret"
clients, codes, access, refresh = {}, {}, set(), set()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def form(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        if self.headers.get("Content-Type", "").startswith("application/json"):
            return json.loads(raw or "{}")
        return {k: v[0] for k, v in parse_qs(raw).items()}

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/.well-known/oauth-protected-resource":
            return self.reply(200, {"resource": f"{BASE}/mcp", "authorization_servers": [BASE], "scopes_supported": ["mcp"]})
        if url.path == "/.well-known/oauth-authorization-server":
            meta = {"issuer": BASE, "authorization_endpoint": f"{BASE}/authorize", "token_endpoint": f"{BASE}/token",
                    "code_challenge_methods_supported": ["S256"]}
            if not FIXED:
                meta["registration_endpoint"] = f"{BASE}/register"
            return self.reply(200, meta)
        if url.path == "/authorize":
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if FIXED:
                assert q["client_id"] == FIXED_ID and q["scope"] == "repo read:user"
            else:
                assert q["client_id"] in clients and q["redirect_uri"] in clients[q["client_id"]]
            assert q["code_challenge_method"] == "S256" and q["resource"] == f"{BASE}/mcp"
            code = secrets.token_hex(8)
            codes[code] = q
            target = q["redirect_uri"] + "?" + urlencode({"code": code, "state": q["state"]})
            return self.reply(302, headers={"Location": target})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/register":
            if FIXED:
                return self.reply(404, {"error": "not found"})
            body = self.form()
            client_id = secrets.token_hex(6)
            clients[client_id] = body["redirect_uris"]
            return self.reply(201, {"client_id": client_id, **body})
        if url.path == "/token":
            body = self.form()
            if FIXED and (body.get("client_id") != FIXED_ID or body.get("client_secret") != FIXED_SECRET):
                return self.reply(401, {"error": "invalid_client"})
            if body["grant_type"] == "authorization_code":
                flow = codes.pop(body["code"], None)
                challenge = base64.urlsafe_b64encode(hashlib.sha256(body["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                if not flow or challenge != flow["code_challenge"] or body["redirect_uri"] != flow["redirect_uri"]:
                    return self.reply(400, {"error": "invalid_grant"})
            elif body["grant_type"] != "refresh_token" or body["refresh_token"] not in refresh:
                return self.reply(400, {"error": "invalid_grant"})
            token, renew = "at-" + secrets.token_hex(6), "rt-" + secrets.token_hex(6)
            access.add(token)
            refresh.add(renew)
            return self.reply(200, {"access_token": token, "refresh_token": renew, "token_type": "Bearer", "expires_in": 3600})
        if url.path == "/admin/expire":
            access.clear()
            return self.reply(200, {})
        if url.path == "/mcp":
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if token not in access:
                return self.reply(401, {"error": "unauthorized"}, {
                    "WWW-Authenticate": f'Bearer resource_metadata="{BASE}/.well-known/oauth-protected-resource", scope="mcp"'})
            message = self.form()
            if "id" not in message:
                return self.reply(202)
            method = message["method"]
            if method == "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "secure"}}
            elif method == "tools/list":
                result = {"tools": [{"name": "whoami", "inputSchema": {"type": "object"}}]}
            elif method == "tools/call":
                result = {"content": [{"type": "text", "text": token}]}
            else:
                result = {}
            return self.reply(200, {"jsonrpc": "2.0", "id": message["id"], "result": result})
        self.reply(404, {"error": "not found"})


class Server(ThreadingHTTPServer):
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


Server(("127.0.0.1", PORT), Handler).serve_forever()
