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
sys.path.insert(0, str(ROOT))

import hub as hub_module  # noqa: E402
import secrets_store  # noqa: E402


def keychain_works():
    if not secrets_store.keychain_available():
        return False
    probe = "selftest/probe"
    try:
        secrets_store.store_keychain(probe, "probe")
        return secrets_store.read_keychain(probe) == "probe"
    except secrets_store.SecretError:
        return False
    finally:
        secrets_store.delete_keychain(probe)


KEYCHAIN = keychain_works()


class KeychainRequirementTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("MCP_HUB_REQUIRE_KEYCHAIN"), "only enforced in CI")
    def test_keychain_is_usable(self):
        self.assertTrue(KEYCHAIN, "MCP_HUB_REQUIRE_KEYCHAIN is set, but no keychain is usable")
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
            "alpha": {"command": DUMMY[0], "args": DUMMY[1:], "env": {"DUMMY_SECRET": "plain-text"}},
            "beta": {"command": DUMMY[0], "args": DUMMY[1:]},
        }}
        Path(cls.home.name, "servers.json").write_text(json.dumps(servers))
        env = {**os.environ, "MCP_HUB_HOME": cls.home.name, "PORT": str(cls.port), "MCP_HUB_TEST_VALUE": "from-env",
               "MCP_HUB_UPDATE_API": "http://127.0.0.1:9", "MCP_HUB_CLIENT_HOME": str(Path(cls.home.name) / "clients"),
               "MCP_HUB_ON_DEMAND_IDLE": "3"}
        cls.proc = subprocess.Popen([sys.executable, str(ROOT / "app.py")], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.wait_for(lambda: len(cls.get("/api/hub")) == 2 and all(
            s["state"] == "running" for s in cls.get("/api/hub").values()))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(10)
        cls.home.cleanup()
        if KEYCHAIN:
            secrets_store.delete_keychain(KEYCHAIN_NAME)

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
        raise AssertionError("condition not met")

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
        result = self.rpc("tools/call", {"name": "beta__echo", "arguments": {"text": "hello"}})["result"]
        self.assertEqual(result["content"][0]["text"], "hello")
        last = self.get("/api/calls?limit=1")[0]
        self.assertEqual((last["server"], last["target"], last["ok"]), ("beta", "echo", True))
        self.assertGreaterEqual(self.get("/api/usage")["beta"]["count"], 1)

    def test_stats_summarize_calls(self):
        self.rpc("tools/call", {"name": "alpha__echo", "arguments": {"text": "x"}})
        self.rpc("tools/call", {"name": "alpha__fail"})
        stats = self.get("/api/stats?days=7")
        self.assertEqual(len(stats["days"]), 7)
        self.assertGreaterEqual(stats["total"], 2)
        self.assertGreaterEqual(stats["errors"], 1)
        alpha = next(s for s in stats["servers"] if s["server"] == "alpha")
        self.assertGreaterEqual(alpha["errors"], 1)
        self.assertEqual(sum(d["ok"] + d["errors"] for d in stats["days"]), stats["total"])
        self.assertTrue(any(t["tool"] == "fail" for t in stats["slowest"]) or len(stats["slowest"]) == 5)

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
            self.assertIn("disabled", body["error"]["message"])
            self.assertEqual(self.get("/api/hub")["alpha"]["tools"], 3)
        finally:
            del servers["alpha"]["disabledTools"]
            self.save_servers(servers)
            self.wait_for(lambda: "alpha__fail" in self.tool_names())

    def test_profiles_save_apply_and_delete(self):
        self.request("POST", "/api/profiles", {"action": "save", "name": "everything"})
        servers = self.servers()
        servers["beta"]["enabled"] = False
        self.save_servers(servers)
        self.wait_for(lambda: "beta__echo" not in self.tool_names())
        self.request("POST", "/api/profiles", {"action": "save", "name": "without-beta"})
        try:
            self.request("POST", "/api/profiles", {"action": "apply", "name": "everything"})
            self.wait_for(lambda: "beta__echo" in self.tool_names())
            self.assertEqual(self.get("/api/state")["profiles"]["active"], "everything")
            self.request("POST", "/api/profiles", {"action": "apply", "name": "without-beta"})
            self.wait_for(lambda: "beta__echo" not in self.tool_names())
        finally:
            for name in ("everything", "without-beta"):
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

    @unittest.skipUnless(KEYCHAIN, "no usable keychain (macOS keychain or Secret Service)")
    def test_keychain_secret_is_resolved(self):
        status, body = self.request("POST", "/api/secrets", {"name": KEYCHAIN_NAME, "value": "from-the-keychain"})
        self.assertEqual(status, 200, body)
        servers = self.servers()
        servers["alpha"]["env"]["DUMMY_SECRET"] = body["ref"]
        self.save_servers(servers)
        try:
            self.wait_for(lambda: self.rpc("tools/call", {"name": "alpha__secret"})["result"]["content"][0]["text"]
                          == "from-the-keychain")
        finally:
            servers["alpha"]["env"]["DUMMY_SECRET"] = "plain-text"
            self.save_servers(servers)
            self.wait_for(lambda: self.rpc("tools/call", {"name": "alpha__secret"})["result"]["content"][0]["text"]
                          == "plain-text")

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
        self.request("POST", "/api/profiles", {"action": "save", "name": "narrow"})
        del servers["alpha"]["disabledTools"]
        servers["beta"]["enabled"] = True
        self.save_servers(servers)
        try:
            self.wait_for(lambda: "beta__echo" in self.tool_names() and "alpha__fail" in self.tool_names())
            self.assertEqual(self.tool_names("/p/narrow/mcp"), ["alpha__echo", "alpha__secret", "alpha__where"])
            body = self.rpc("tools/call", {"name": "beta__echo", "arguments": {"text": "x"}}, path="/p/narrow/mcp")
            self.assertIn("error", body)
            self.rpc("tools/call", {"name": "alpha__echo", "arguments": {"text": "x"}}, path="/p/narrow/mcp")
            self.assertTrue(self.get("/api/calls?limit=1")[0]["client"].endswith("· narrow"))
            self.assertIn("beta__echo", self.tool_names())
            body = self.rpc("initialize", {"protocolVersion": "2025-06-18"}, path="/p/does-not-exist/mcp")
            self.assertIn("Unknown profile", body["error"]["message"])
        finally:
            self.request("POST", "/api/profiles", {"action": "delete", "name": "narrow"})

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

    def test_clients_endpoint_tracks_sessions(self):
        req = urllib.request.Request(self.base + "/mcp", json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "tester", "version": "1.2"}}}).encode(),
            {"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as response:
            session_id = response.headers["Mcp-Session-Id"]
        headers = {"Mcp-Session-Id": session_id}
        self.request("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                      "params": {"name": "alpha__echo", "arguments": {"text": "x"}}}, headers)
        row = next(c for c in self.get("/api/clients") if c["id"] == session_id[:8])
        self.assertEqual((row["name"], row["version"], row["calls"], row["requests"], row["streams"], row["profile"]),
                         ("tester", "1.2", 1, 2, 0, None))
        self.request("DELETE", "/mcp", None, headers)
        self.assertFalse(any(c["id"] == session_id[:8] for c in self.get("/api/clients")))

    def test_update_check_failure_is_reported_not_fatal(self):
        status, body = self.request("POST", "/api/update/check", {})
        self.assertEqual(status, 200, body)
        self.assertIn("Update check failed", body["error"])
        self.assertEqual((body["available"], body["method"]), (False, "git" if (ROOT / ".git").exists() else "archive"))
        status, body = self.request("POST", "/api/update/apply", {})
        self.assertEqual((status, body["error"]), (409, "No newer version available"))

    def test_compact_endpoint_searches_describes_and_calls(self):
        path = "/mcp/compact"
        self.assertEqual(self.tool_names(path), ["call_tool", "describe_tool", "search_tools"])
        init = self.rpc("initialize", {"protocolVersion": "2025-06-18"}, path=path)["result"]
        self.assertIn("call search_tools", init["instructions"])
        self.assertIn("- alpha", init["instructions"])

        def meta(name, arguments):
            return self.rpc("tools/call", {"name": name, "arguments": arguments}, path=path)["result"]

        found = meta("search_tools", {"query": "working directory"})["content"][0]["text"].splitlines()
        self.assertEqual({line.split(":")[0] for line in found[:2]}, {"alpha__where", "beta__where"})
        self.assertEqual(meta("search_tools", {"query": "", "server": "beta"})["content"][0]["text"].count("beta__"), 4)
        self.assertIn('"inputSchema"', meta("describe_tool", {"name": "alpha__echo"})["content"][0]["text"])
        self.assertTrue(meta("describe_tool", {"name": "alpha__nope"})["isError"])
        self.assertEqual(meta("call_tool", {"name": "alpha__echo", "arguments": {"text": "kompakt"}})["content"][0]["text"], "kompakt")
        self.assertEqual(self.get("/api/calls?limit=1")[0]["target"], "echo")
        self.assertTrue(meta("call_tool", {"name": "alpha__nope"})["isError"])
        sizes = self.get("/api/compact")
        self.assertLess(sizes["compactChars"], sizes["fullChars"] * 2)

    def test_crashed_server_is_restarted(self):
        result = self.rpc("tools/call", {"name": "beta__fail", "arguments": {"exit": True}})["result"]
        self.assertTrue(result["isError"])
        self.wait_for(lambda: self.get("/api/hub")["beta"]["state"] == "running" and self.get("/api/hub")["beta"]["restarts"] == 1)
        self.assertEqual(self.call_text("beta__echo"), "")
        self.assertIn("stopped unexpectedly", self.get("/api/hub")["beta"]["lastError"])
        self.assertEqual(self.request("POST", "/api/hub/restart", {"name": "nope"})[0], 404)

    def test_integrations_connect_export_and_disconnect(self):
        cursor = Path(self.home.name) / "clients" / ".cursor" / "mcp.json"
        cursor.parent.mkdir(parents=True)
        cursor.write_text(json.dumps({"mcpServers": {"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]}}}))
        row = next(r for r in self.get("/api/integrations") if r["id"] == "cursor")
        self.assertEqual((row["installed"], row["connected"], row["importable"]), (True, False, ["fetch"]))
        status, rows = self.request("POST", "/api/integrations/connect", {"id": "cursor", "compact": True})
        self.assertEqual(status, 200, rows)
        self.assertTrue(next(r for r in rows if r["id"] == "cursor")["compact"])
        self.assertEqual(json.loads(cursor.read_text())["mcpServers"]["mcp-hub"]["url"], f"{self.base}/mcp/compact")
        status, exported = self.request("POST", "/api/integrations/export", {"id": "cursor"})
        self.assertEqual(exported["servers"], ["fetch"])
        self.request("POST", "/api/integrations/disconnect", {"id": "cursor"})
        self.assertNotIn("mcp-hub", json.loads(cursor.read_text())["mcpServers"])
        self.assertEqual(self.request("POST", "/api/integrations/connect", {"id": "nope"})[0], 409)

    def test_profile_endpoint_starts_switched_off_servers_on_demand(self):
        self.request("POST", "/api/profiles", {"action": "save", "name": "wide"})
        servers = self.servers()
        servers["beta"]["enabled"] = False
        self.save_servers(servers)
        try:
            self.wait_for(lambda: "beta" not in self.get("/api/hub"))
            self.assertIn("beta__echo", self.tool_names("/p/wide/mcp"))
            self.assertNotIn("beta__echo", self.tool_names())
            self.assertTrue(self.get("/api/hub")["beta"]["onDemand"])
            body = self.rpc("tools/call", {"name": "beta__echo", "arguments": {"text": "on demand"}}, path="/p/wide/mcp")
            self.assertEqual(body["result"]["content"][0]["text"], "on demand")
            self.wait_for(lambda: "beta" not in self.get("/api/hub"))
            self.assertIn("beta__echo", self.tool_names("/p/wide/mcp"))
        finally:
            self.request("POST", "/api/profiles", {"action": "delete", "name": "wide"})
            servers["beta"]["enabled"] = True
            self.save_servers(servers)
            self.wait_for(lambda: "beta__echo" in self.tool_names())
            self.assertNotIn("onDemand", self.get("/api/hub")["beta"])

    def test_requests_need_the_hub_host_and_origin(self):
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": f"attacker.example:{self.port}"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={"Origin": "http://localhost:3000"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={"Origin": f"http://localhost:{self.port}"})[0], 200)
        req = urllib.request.Request(self.base + "/api/settings", b"{}", {"Content-Type": "text/plain"}, method="PUT")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req)
        self.assertEqual(caught.exception.code, 415)
        caught.exception.close()
        req = urllib.request.Request(self.base + "/api/import/parse", b"{oops", {"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()
        self.assertEqual(self.request("GET", "/api/stats?days=abc")[0], 200)

    def call_text(self, tool):
        return self.rpc("tools/call", {"name": tool})["result"]["content"][0]["text"]

    def test_cwd_env_reference_and_enabled_tools(self):
        servers = self.servers()
        original = json.loads(json.dumps(servers["alpha"]))
        with tempfile.TemporaryDirectory() as folder:
            servers["alpha"].update(cwd=folder, enabledTools=["secret", "where"])
            servers["alpha"]["env"]["DUMMY_SECRET"] = "${env:MCP_HUB_TEST_VALUE}"
            self.save_servers(servers)
            try:
                self.wait_for(lambda: "alpha__echo" not in self.tool_names())
                self.assertEqual(Path(self.call_text("alpha__where")).resolve(), Path(folder).resolve())
                self.assertEqual(self.call_text("alpha__secret"), "from-env")
                self.assertIn("disabled", self.rpc("tools/call", {"name": "alpha__echo"})["error"]["message"])
                self.assertEqual(self.get("/api/hub")["alpha"]["tools"], 2)
            finally:
                servers["alpha"] = original
                self.save_servers(servers)
                self.wait_for(lambda: "alpha__echo" in self.tool_names())

    def test_import_parse_endpoint(self):
        status, body = self.request("POST", "/api/import/parse", {"text": "[mcp_servers.alpha]\ncommand = \"npx\"\n\n[mcp_servers.new]\nurl = \"https://example.com/mcp\"\n"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["format"], "toml-codex")
        self.assertEqual(sorted(body["servers"]), ["alpha", "new"])
        self.assertEqual(body["existing"], ["alpha"])
        status, body = self.request("POST", "/api/import/parse", {"text": "nonsense"})
        self.assertEqual(status, 400)

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
        self.send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "alpha__echo", "arguments": {"text": "back"}}})
        self.assertEqual(self.reply(3)["result"]["content"][0]["text"], "back")
        HubTest.wait_for(lambda: self.live() == ["desktop-test"])


@unittest.skipUnless(KEYCHAIN, "tokens live in the keychain (macOS keychain or Secret Service)")
class OAuthTest(unittest.TestCase):
    NAME = "selftest-oauth"
    PROVIDER_ARGS = []
    ENTRY_EXTRA = {}

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.oauth_port, self.port = free_port(), free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.oauth_base = f"http://127.0.0.1:{self.oauth_port}"
        self.provider = subprocess.Popen([sys.executable, str(ROOT / "tests" / "dummy_oauth_server.py"), str(self.oauth_port), *self.PROVIDER_ARGS],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        HubTest.wait_for(lambda: fetch(self.oauth_base + "/.well-known/oauth-protected-resource"))
        Path(self.home.name, "servers.json").write_text(json.dumps(
            {"mcpServers": {self.NAME: {"type": "http", "url": self.oauth_base + "/mcp", **self.ENTRY_EXTRA}}}))
        env = {**os.environ, "MCP_HUB_HOME": self.home.name, "PORT": str(self.port)}
        self.hub = subprocess.Popen([sys.executable, str(ROOT / "app.py")], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def tearDown(self):
        for proc in (self.hub, self.provider):
            proc.terminate()
            proc.wait(10)
        self.home.cleanup()
        secrets_store.delete_keychain(f"oauth/{self.NAME}")

    def state(self):
        return fetch(self.base + "/api/hub").get(self.NAME, {})

    def call(self):
        return fetch(self.base + "/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                     "params": {"name": f"{self.NAME}__whoami"}}).encode())

    def test_login_refresh_and_logout(self):
        HubTest.wait_for(lambda: self.state().get("state") == "auth")
        self.assertFalse(self.state()["oauth"]["signedIn"])

        start = fetch(self.base + "/api/oauth/start", json.dumps({"name": self.NAME}).encode())
        self.assertIn("code_challenge_method=S256", start["url"])
        with urllib.request.urlopen(start["url"]) as response:
            self.assertIn("Signed in", response.read().decode())
        HubTest.wait_for(lambda: self.state().get("state") == "running")
        self.assertTrue(self.state()["oauth"]["signedIn"])
        first = self.call()["result"]["content"][0]["text"]
        self.assertTrue(first.startswith("at-"))

        fetch(self.oauth_base + "/admin/expire", b"{}")
        second = self.call()["result"]["content"][0]["text"]
        self.assertTrue(second.startswith("at-"))
        self.assertNotEqual(first, second)

        fetch(self.base + "/api/oauth/logout", json.dumps({"name": self.NAME}).encode())
        HubTest.wait_for(lambda: self.state().get("state") == "auth")
        self.assertFalse(self.state()["oauth"]["signedIn"])


class FixedClientOAuthTest(OAuthTest):
    PROVIDER_ARGS = ["--fixed-client"]
    ENTRY_EXTRA = {"oauth": {"clientId": "fixed-id", "clientSecret": "fixed-secret", "scopes": "repo read:user"}}

    def test_without_client_id_explains_what_to_do(self):
        HubTest.wait_for(lambda: self.state().get("state") == "auth")
        servers = {self.NAME: {"type": "http", "url": self.oauth_base + "/mcp"}}
        fetch(self.base + "/api/servers", json.dumps({"mcpServers": servers}).encode(), "PUT")
        req = urllib.request.Request(self.base + "/api/oauth/start", json.dumps({"name": self.NAME}).encode(),
                                     {"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req)
        with error.exception as e:
            self.assertIn("client ID", json.loads(e.read())["error"])


if __name__ == "__main__":
    unittest.main()


class RestartPolicyTest(unittest.TestCase):
    class Fake:
        def __init__(self, name, started_at=None):
            self.name, self.started_at = name, started_at

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.hub = hub_module.Hub(lambda: {"mcpServers": {}}, lambda: {"passEnvironment": True}, self.home.name)

    def tearDown(self):
        self.home.cleanup()

    def test_delays_grow_and_the_hub_gives_up(self):
        upstream, now, waits = self.Fake("x"), 1000.0, []
        for _ in hub_module.RESTART_DELAYS:
            self.hub._schedule_restart(upstream, now)
            info = self.hub.restarts["x"]
            waits.append(info["retryAt"] - now)
            info["retryAt"] = None
        self.assertEqual(tuple(waits), hub_module.RESTART_DELAYS)
        self.hub._schedule_restart(upstream, now)
        self.assertTrue(self.hub.restarts["x"]["gaveUp"])

    def test_a_stable_run_resets_the_failures(self):
        self.hub.restarts["x"] = {"count": 3, "failures": 3, "retryAt": None, "gaveUp": False}
        self.hub._schedule_restart(self.Fake("x", started_at=0), hub_module.STABLE_AFTER + 1)
        self.assertEqual(self.hub.restarts["x"]["failures"], 1)
