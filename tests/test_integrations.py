import json
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import importer
import integrations

PORT = 4747
URL = f"http://127.0.0.1:{PORT}/mcp"
BRIDGE = {"python": "/usr/bin/python3", "script": "/opt/mcp-hub/bridge.py"}


class IntegrationsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        patcher = mock.patch.dict(os.environ, {"MCP_HUB_CLIENT_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.paths = {c["id"]: c["path"] for c in integrations.clients()}

    def write(self, client_id, text):
        path = self.paths[client_id]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def row(self, client_id):
        return next(r for r in integrations.status(PORT) if r["id"] == client_id)

    def test_missing_clients_are_not_installed(self):
        row = self.row("cursor")
        self.assertEqual((row["installed"], row["connected"], row["importable"]), (False, False, []))
        self.assertTrue(row["display"].startswith("~"))

    def test_json_client_connect_switch_and_disconnect(self):
        path = self.write("cursor", json.dumps({"mcpServers": {"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
                                                              "old-hub": {"url": "http://localhost:4747/mcp"}}, "other": 1}))
        self.assertEqual((self.row("cursor")["connected"], self.row("cursor")["importable"]), (True, ["fetch"]))
        integrations.connect("cursor", URL + "/compact", PORT, BRIDGE)
        data = json.loads(path.read_text())
        self.assertEqual(data["mcpServers"], {"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
                                              "mcp-hub": {"url": URL + "/compact"}})
        self.assertEqual(data["other"], 1)
        self.assertEqual(len(list(path.parent.glob("mcp.json.mcp-hub-*.bak"))), 1)
        self.assertTrue(self.row("cursor")["compact"])
        integrations.disconnect("cursor", PORT)
        self.assertEqual(list(json.loads(path.read_text())["mcpServers"]), ["fetch"])
        self.assertFalse(self.row("cursor")["connected"])

    def test_entry_shapes_per_client(self):
        for client_id in ("claude-desktop", "vscode", "copilot"):
            self.write(client_id, "{}")
            integrations.connect(client_id, URL, PORT, BRIDGE)
        desktop = json.loads(self.paths["claude-desktop"].read_text())["mcpServers"]["mcp-hub"]
        self.assertEqual(desktop, {"command": "/usr/bin/python3", "args": ["/opt/mcp-hub/bridge.py", URL]})
        self.assertEqual(json.loads(self.paths["vscode"].read_text())["servers"]["mcp-hub"], {"type": "http", "url": URL})
        self.assertEqual(json.loads(self.paths["copilot"].read_text())["mcpServers"]["mcp-hub"],
                         {"type": "http", "url": URL, "tools": ["*"]})
        self.assertTrue(all(self.row(c)["connected"] for c in ("claude-desktop", "vscode", "copilot")))

    def test_json_with_comments_is_left_alone(self):
        path = self.write("vscode", '{ // mine\n "servers": {} }')
        self.assertIn("not plain JSON", self.row("vscode")["error"])
        with self.assertRaises(integrations.IntegrationError):
            integrations.connect("vscode", URL, PORT, BRIDGE)
        self.assertEqual(path.read_text(), '{ // mine\n "servers": {} }')

    def test_export_and_remove_json(self):
        self.write("cursor", json.dumps({"mcpServers": {"a": {"command": "x"}, "b": {"url": "https://b/mcp"},
                                                        "mcp-hub": {"url": URL}}}))
        exported = integrations.export("cursor", PORT)
        self.assertEqual(exported["servers"], ["a", "b"])
        self.assertEqual(sorted(importer.parse(exported["text"], PORT)["servers"]), ["a", "b"])
        integrations.remove("cursor", ["a"])
        self.assertEqual(sorted(json.loads(self.paths["cursor"].read_text())["mcpServers"]), ["b", "mcp-hub"])

    CODEX = '''model = "o4"

[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp"]

[mcp_servers.context7.env]
KEY = "1"

[mcp_servers."my server"]
url = "https://example.com/mcp"

[mcp_servers.legacy-hub]
url = "http://127.0.0.1:4747/mcp"

[profiles.fast]
model = "o4-mini"
'''

    def test_codex_connect_export_and_remove(self):
        path = self.write("codex", self.CODEX)
        row = self.row("codex")
        self.assertEqual((row["connected"], row["importable"]), (True, ["context7", "my server"]))
        integrations.connect("codex", URL, PORT, BRIDGE)
        data = tomllib.loads(path.read_text())
        self.assertEqual(sorted(data["mcp_servers"]), ["context7", "mcp-hub", "my server"])
        self.assertEqual(data["mcp_servers"]["mcp-hub"], {"url": URL})
        self.assertEqual(data["mcp_servers"]["context7"]["env"], {"KEY": "1"})
        self.assertEqual(data["profiles"], {"fast": {"model": "o4-mini"}})
        exported = integrations.export("codex", PORT)
        self.assertEqual(sorted(importer.parse(exported["text"], PORT)["servers"]), ["context7", "my server"])
        self.assertNotIn("model", exported["text"])
        self.assertNotIn("profiles", exported["text"])
        integrations.remove("codex", ["context7", "my server"])
        data = tomllib.loads(path.read_text())
        self.assertEqual((sorted(data["mcp_servers"]), data["model"]), (["mcp-hub"], "o4"))
        integrations.disconnect("codex", PORT)
        self.assertNotIn("mcp_servers", tomllib.loads(path.read_text()))

    def test_every_change_keeps_its_own_backup(self):
        path = self.write("cursor", json.dumps({"mcpServers": {"a": {"command": "x"}, "b": {"command": "y"}}}))
        original = path.read_text()
        integrations.remove("cursor", ["a"])
        integrations.connect("cursor", URL, PORT, BRIDGE)
        backups = sorted(path.parent.glob("mcp.json.mcp-hub-*.bak"), key=lambda p: p.stat().st_mtime_ns)
        self.assertEqual(len(backups), 2)
        self.assertEqual(backups[0].read_text(), original)
        for _ in range(integrations.KEEP_BACKUPS + 2):
            integrations.connect("cursor", URL, PORT, BRIDGE)
        self.assertEqual(len(list(path.parent.glob("mcp.json.mcp-hub-*.bak"))), integrations.KEEP_BACKUPS)

    def test_codex_connect_creates_the_file(self):
        self.paths["codex"].parent.mkdir(parents=True)
        integrations.connect("codex", URL, PORT, BRIDGE)
        self.assertEqual(tomllib.loads(self.paths["codex"].read_text()), {"mcp_servers": {"mcp-hub": {"url": URL}}})

    def test_inline_server_tables_are_refused(self):
        path = self.write("codex", 'mcp_servers = { a = { command = "x" } }\n')
        with self.assertRaisesRegex(integrations.IntegrationError, "cleanly"):
            integrations.remove("codex", ["a"])
        self.assertEqual(path.read_text(), 'mcp_servers = { a = { command = "x" } }\n')


if __name__ == "__main__":
    unittest.main()
