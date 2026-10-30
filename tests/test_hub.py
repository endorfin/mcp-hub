import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DUMMY = [sys.executable, str(ROOT / "tests" / "dummy_server.py")]
KEYCHAIN_NAME = "selftest/hub-tests"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class HubTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.TemporaryDirectory()
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        servers = {"mcpServers": {
            "alpha": {"command": DUMMY[0], "args": DUMMY[1:], "env": {"DUMMY_SECRET": "klartext"}},
            "beta": {"command": DUMMY[0], "args": DUMMY[1:]},
        }}
        Path(cls.home.name, "servers.json").write_text(json.dumps(servers))
        env = {**os.environ, "MCP_HUB_HOME": cls.home.name, "PORT": str(cls.port)}
        cls.proc = subprocess.Popen([sys.executable, str(ROOT / "app.py")], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.wait_for(lambda: len(cls.get("/api/hub")) == 2 and all(
            s["state"] == "running" for s in cls.get("/api/hub").values()))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(10)
        cls.home.cleanup()
        if sys.platform == "darwin":
            subprocess.run(["security", "delete-generic-password", "-a", "mcp-hub", "-s", f"mcp-hub/{KEYCHAIN_NAME}"],
                           capture_output=True)

    @classmethod
    def request(cls, method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(cls.base + path, data, {"Content-Type": "application/json", **(headers or {})},
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"null")

    @classmethod
    def get(cls, path):
        try:
            return cls.request("GET", path)[1]
        except OSError:
            return {}

    @classmethod
    def wait_for(cls, condition, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if condition():
                    return
            except (OSError, KeyError, TypeError):
                pass
            time.sleep(0.2)
        raise AssertionError("Bedingung nicht erfüllt")

    def rpc(self, method, params=None, path="/mcp"):
        status, body = self.request("POST", path, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
        self.assertEqual(status, 200, body)
        return body

    def tool_names(self, path="/mcp"):
        return sorted(t["name"] for t in self.rpc("tools/list", path=path)["result"]["tools"])

    def servers(self):
        return self.get("/api/state")["config"]["mcpServers"]

    def save_servers(self, servers):
        status, body = self.request("PUT", "/api/servers", {"mcpServers": servers})
        self.assertEqual(status, 200, body)

    def test_tools_are_prefixed_and_titled(self):
        tools = {t["name"]: t for t in self.rpc("tools/list")["result"]["tools"]}
        self.assertIn("alpha__echo", tools)
        self.assertIn("beta__echo", tools)
        self.assertEqual(tools["alpha__echo"]["title"], "alpha: Echo")

    def test_call_is_routed_and_logged(self):
        result = self.rpc("tools/call", {"name": "beta__echo", "arguments": {"text": "hallo"}})["result"]
        self.assertEqual(result["content"][0]["text"], "hallo")
        last = self.get("/api/calls?limit=1")[0]
        self.assertEqual((last["server"], last["target"], last["ok"]), ("beta", "echo", True))
        self.assertGreaterEqual(self.get("/api/usage")["beta"]["count"], 1)

    def test_upstream_error_becomes_tool_error(self):
        result = self.rpc("tools/call", {"name": "alpha__fail"})["result"]
        self.assertTrue(result["isError"])

    def test_disabled_tools_are_hidden_and_rejected(self):
        servers = self.servers()
        servers["alpha"]["disabledTools"] = ["fail"]
        self.save_servers(servers)
        try:
            self.wait_for(lambda: "alpha__fail" not in self.tool_names())
            body = self.rpc("tools/call", {"name": "alpha__fail"})
            self.assertIn("deaktiviert", body["error"]["message"])
            self.assertEqual(self.get("/api/hub")["alpha"]["tools"], 2)
        finally:
            del servers["alpha"]["disabledTools"]
            self.save_servers(servers)
            self.wait_for(lambda: "alpha__fail" in self.tool_names())

    def test_profiles_save_apply_and_delete(self):
        self.request("POST", "/api/profiles", {"action": "save", "name": "voll"})
        servers = self.servers()
        servers["beta"]["enabled"] = False
        self.save_servers(servers)
        self.wait_for(lambda: "beta__echo" not in self.tool_names())
        self.request("POST", "/api/profiles", {"action": "save", "name": "ohne-beta"})
        try:
            self.request("POST", "/api/profiles", {"action": "apply", "name": "voll"})
            self.wait_for(lambda: "beta__echo" in self.tool_names())
            self.assertEqual(self.get("/api/state")["profiles"]["active"], "voll")
            self.request("POST", "/api/profiles", {"action": "apply", "name": "ohne-beta"})
            self.wait_for(lambda: "beta__echo" not in self.tool_names())
        finally:
            for name in ("voll", "ohne-beta"):
                self.request("POST", "/api/profiles", {"action": "delete", "name": name})
            servers = self.servers()
            servers["beta"]["enabled"] = True
            self.save_servers(servers)
            self.wait_for(lambda: "beta__echo" in self.tool_names())
        self.assertEqual(self.get("/api/state")["profiles"], {"active": None, "profiles": {}})

    def test_no_profile_enables_everything(self):
        servers = self.servers()
        servers["alpha"]["disabledTools"] = ["fail"]
        servers["beta"]["enabled"] = False
        self.save_servers(servers)
        self.wait_for(lambda: "beta__echo" not in self.tool_names())
        self.request("POST", "/api/profiles", {"action": "clear"})
        self.wait_for(lambda: "beta__echo" in self.tool_names() and "alpha__fail" in self.tool_names())
        servers = self.servers()
        self.assertNotIn("disabledTools", servers["alpha"])
        self.assertTrue(servers["beta"]["enabled"])

    @unittest.skipUnless(sys.platform == "darwin", "Schlüsselbund nur auf macOS")
    def test_keychain_secret_is_resolved(self):
        status, body = self.request("POST", "/api/secrets", {"name": KEYCHAIN_NAME, "value": "aus-dem-schluesselbund"})
        self.assertEqual(status, 200, body)
        servers = self.servers()
        servers["alpha"]["env"]["DUMMY_SECRET"] = body["ref"]
        self.save_servers(servers)
        try:
            self.wait_for(lambda: self.rpc("tools/call", {"name": "alpha__secret"})["result"]["content"][0]["text"]
                          == "aus-dem-schluesselbund")
        finally:
            servers["alpha"]["env"]["DUMMY_SECRET"] = "klartext"
            self.save_servers(servers)
            self.wait_for(lambda: self.rpc("tools/call", {"name": "alpha__secret"})["result"]["content"][0]["text"]
                          == "klartext")

    def test_clients_are_notified_about_changes(self):
        received = []
        req = urllib.request.Request(self.base + "/mcp", headers={"Accept": "text/event-stream"})
        stream = urllib.request.urlopen(req, timeout=30)

        def listen():
            for line in stream:
                if line.startswith(b"data:"):
                    received.append(json.loads(line[5:])["method"])

        threading.Thread(target=listen, daemon=True).start()
        self.wait_for(lambda: len(self.get("/api/live")) == 1)
        servers = self.servers()
        servers["beta"]["disabledTools"] = ["echo"]
        self.save_servers(servers)
        try:
            self.wait_for(lambda: "notifications/tools/list_changed" in received)
        finally:
            del servers["beta"]["disabledTools"]
            self.save_servers(servers)
            self.wait_for(lambda: "beta__echo" in self.tool_names())

    def test_profile_endpoint_serves_its_own_view(self):
        servers = self.servers()
        servers["alpha"]["disabledTools"] = ["fail"]
        servers["beta"]["enabled"] = False
        self.save_servers(servers)
        self.request("POST", "/api/profiles", {"action": "save", "name": "schmal"})
        del servers["alpha"]["disabledTools"]
        servers["beta"]["enabled"] = True
        self.save_servers(servers)
        try:
            self.wait_for(lambda: "beta__echo" in self.tool_names() and "alpha__fail" in self.tool_names())
            self.assertEqual(self.tool_names("/p/schmal/mcp"), ["alpha__echo", "alpha__secret"])
            body = self.rpc("tools/call", {"name": "beta__echo", "arguments": {"text": "x"}}, path="/p/schmal/mcp")
            self.assertIn("error", body)
            self.rpc("tools/call", {"name": "alpha__echo", "arguments": {"text": "x"}}, path="/p/schmal/mcp")
            self.assertTrue(self.get("/api/calls?limit=1")[0]["client"].endswith("· schmal"))
            self.assertIn("beta__echo", self.tool_names())
            body = self.rpc("initialize", {"protocolVersion": "2025-06-18"}, path="/p/gibts-nicht/mcp")
            self.assertIn("Unbekanntes Profil", body["error"]["message"])
        finally:
            self.request("POST", "/api/profiles", {"action": "delete", "name": "schmal"})

    def test_unknown_and_ended_sessions_get_404(self):
        status, body = self.request("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                    {"Mcp-Session-Id": "gibt-es-nicht"})
        self.assertEqual(status, 404, body)
        req = urllib.request.Request(self.base + "/mcp", json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}).encode(),
            {"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as response:
            session_id = response.headers["Mcp-Session-Id"]
        headers = {"Mcp-Session-Id": session_id}
        self.assertEqual(self.request("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers)[0], 200)
        self.request("DELETE", "/mcp", None, headers)
        self.assertEqual(self.request("POST", "/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}, headers)[0], 404)

    def test_cross_origin_writes_are_rejected(self):
        status, _ = self.request("PUT", "/api/servers", {"mcpServers": {}}, {"Origin": "https://example.com"})
        self.assertEqual(status, 403)
        status, _ = self.request("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                 {"Origin": "https://example.com"})
        self.assertEqual(status, 403)
        self.assertEqual(sorted(self.servers()), ["alpha", "beta"])


def fetch(url, data=None, method=None):
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read() or b"null")


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        Path(self.home.name, "servers.json").write_text(json.dumps(
            {"mcpServers": {"alpha": {"command": DUMMY[0], "args": DUMMY[1:]}}}))
        self.start_hub()
        self.lines = []
        self.bridge = subprocess.Popen([sys.executable, str(ROOT / "bridge.py"), self.base + "/mcp"],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        threading.Thread(target=self.read_bridge, daemon=True).start()

    def tearDown(self):
        self.bridge.kill()
        self.bridge.wait(10)
        self.bridge.stdin.close()
        self.bridge.stdout.close()
        self.hub.terminate()
        self.hub.wait(10)
        self.home.cleanup()

    def start_hub(self):
        env = {**os.environ, "MCP_HUB_HOME": self.home.name, "PORT": str(self.port)}
        self.hub = subprocess.Popen([sys.executable, str(ROOT / "app.py")], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        HubTest.wait_for(lambda: fetch(self.base + "/api/hub").get("alpha", {}).get("state") == "running")

    def read_bridge(self):
        for line in self.bridge.stdout:
            self.lines.append(json.loads(line))

    def send(self, message):
        self.bridge.stdin.write((json.dumps(message) + "\n").encode())
        self.bridge.stdin.flush()

    def reply(self, message_id):
        HubTest.wait_for(lambda: any(m.get("id") == message_id for m in self.lines))
        return next(m for m in self.lines if m.get("id") == message_id)

    def notified(self):
        return any(m.get("method") == "notifications/tools/list_changed" for m in self.lines)

    def live(self):
        return fetch(self.base + "/api/live")

    def test_bridge_forwards_requests_notifications_and_survives_restart(self):
        self.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "desktop-test"}}})
        self.assertTrue(self.reply(1)["result"]["capabilities"]["tools"]["listChanged"])
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertIn("alpha__echo", [t["name"] for t in self.reply(2)["result"]["tools"]])
        HubTest.wait_for(lambda: self.live() == ["desktop-test"])

        servers = json.loads(Path(self.home.name, "servers.json").read_text())
        servers["mcpServers"]["alpha"]["disabledTools"] = ["fail"]
        fetch(self.base + "/api/servers", json.dumps(servers).encode(), "PUT")
        HubTest.wait_for(self.notified)

        self.lines.clear()
        self.hub.terminate()
        self.hub.wait(10)
        self.start_hub()
        HubTest.wait_for(self.notified, timeout=40)
        self.send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "alpha__echo", "arguments": {"text": "zurück"}}})
        self.assertEqual(self.reply(3)["result"]["content"][0]["text"], "zurück")
        HubTest.wait_for(lambda: self.live() == ["desktop-test"])


class MigrationTest(unittest.TestCase):
    def test_legacy_config_dir_is_moved(self):
        with tempfile.TemporaryDirectory() as home:
            legacy = Path(home, ".config", "mcp-proxy")
            legacy.mkdir(parents=True)
            Path(legacy, "servers.json").write_text(json.dumps({"mcpServers": {}}))
            Path(legacy, "usage.json").write_text(json.dumps({"alpha": {"count": 3, "last": 1}}))
            port = free_port()
            env = {k: v for k, v in os.environ.items() if k not in ("MCP_HUB_HOME", "MCP_PROXY_GUI_HOME")}
            proc = subprocess.Popen([sys.executable, str(ROOT / "app.py")], env={**env, "HOME": home, "PORT": str(port)},
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                HubTest.wait_for(lambda: fetch(f"http://127.0.0.1:{port}/api/usage") == {"alpha": {"count": 3, "last": 1}})
                state = fetch(f"http://127.0.0.1:{port}/api/state")
                self.assertEqual(state["configPath"], str(Path(home, ".config", "mcp-hub", "servers.json")))
                self.assertFalse(legacy.exists())
            finally:
                proc.terminate()
                proc.wait(10)


if __name__ == "__main__":
    unittest.main()
