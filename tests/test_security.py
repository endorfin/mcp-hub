import json
import os
import stat
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import net
import oauth
from fsutil import atomic_write


class Local(HTTPServer):
    def server_bind(self):
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


def serve(handle):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            handle(self)

        def log_message(self, *args):
            pass

    server = Local(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class NetTest(unittest.TestCase):
    def setUp(self):
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()

    def start(self, handle):
        server = serve(handle)
        self.servers.append(server)
        return f"http://127.0.0.1:{server.server_port}"

    def test_redirects_drop_the_token_on_other_hosts_only(self):
        seen = {}

        def target(handler):
            seen[handler.path] = handler.headers.get("Authorization")
            handler.send_response(200)
            handler.end_headers()
            handler.wfile.write(b"ok")

        other = self.start(target)

        def origin(handler):
            if handler.path == "/same":
                seen["/same"] = handler.headers.get("Authorization")
                handler.send_response(200)
                handler.end_headers()
                return
            location = "/same" if handler.path == "/local" else f"{other}/elsewhere"
            handler.send_response(302)
            handler.send_header("Location", location)
            handler.end_headers()

        base = self.start(origin)
        for path in ("/away", "/local"):
            request = urllib.request.Request(base + path, headers={"Authorization": "Bearer secret"})
            net.opener.open(request, timeout=10).close()
        self.assertEqual(seen, {"/elsewhere": None, "/same": "Bearer secret"})

    def test_url_rules(self):
        self.assertTrue(net.secure_url("https://auth.example.com/authorize"))
        self.assertTrue(net.secure_url("http://127.0.0.1:5555/authorize"))
        self.assertFalse(net.secure_url("http://auth.example.com/authorize"))
        self.assertFalse(net.secure_url("javascript:alert(1)//"))
        self.assertTrue(net.same_origin("https://a.example/sse", "https://a.example/messages?x=1"))
        self.assertFalse(net.same_origin("https://a.example/sse", "https://b.example/messages"))

    def test_oauth_rejects_unsafe_endpoints(self):
        def metadata(handler):
            if handler.path.startswith("/.well-known/oauth-authorization-server"):
                body = json.dumps({"authorization_endpoint": "javascript:alert(document.domain)//",
                                   "token_endpoint": "https://auth.example.com/token"}).encode()
                handler.send_response(200)
                handler.send_header("Content-Type", "application/json")
                handler.end_headers()
                handler.wfile.write(body)
            else:
                handler.send_response(404)
                handler.end_headers()

        base = self.start(metadata)
        with self.assertRaisesRegex(oauth.OAuthError, "authorization endpoint must use https"):
            oauth.discover(base + "/mcp")


@unittest.skipIf(sys.platform == "win32", "POSIX file modes")
class AtomicWriteTest(unittest.TestCase):
    def test_keeps_the_mode_and_creates_private_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "servers.json"
            atomic_write(path, "{}")
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            os.chmod(path, 0o640)
            atomic_write(path, '{"a": 1}')
            self.assertEqual((stat.S_IMODE(os.stat(path).st_mode), path.read_text()), (0o640, '{"a": 1}'))


if __name__ == "__main__":
    unittest.main()
