import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import importer


def reasons(result):
    return {(w["server"], w["key"], w["reason"]) for w in result["warnings"]}


class JsonTest(unittest.TestCase):
    def test_claude_desktop_format(self):
        result = importer.parse('''{"mcpServers": {
            "fetch": {"command": "uvx", "args": ["mcp-server-fetch"], "env": {"A": "1"}},
            "remote": {"url": "https://example.com/mcp", "headers": {"X": "y"}, "autoApprove": ["a"]},
            "broken": {"note": "nothing to start"}}}''')
        self.assertEqual(result["format"], "json-mcpservers")
        self.assertEqual(result["servers"]["fetch"], {"command": "uvx", "args": ["mcp-server-fetch"], "env": {"A": "1"}, "enabled": True})
        self.assertEqual(result["servers"]["remote"], {"type": "http", "url": "https://example.com/mcp", "headers": {"X": "y"}, "enabled": True})
        self.assertEqual(result["skipped"], ["broken"])
        self.assertIn(("remote", "autoApprove", "client"), reasons(result))

    def test_keeps_tags(self):
        result = importer.parse('{"mcpServers": {"fetch": {"command": "uvx", "tags": ["web", "tools"]}}}')
        self.assertEqual(result["servers"]["fetch"]["tags"], ["web", "tools"])
        self.assertEqual(result["warnings"], [])

    def test_vscode_format_with_sse_and_disabled(self):
        result = importer.parse('{"servers": {"old": {"type": "sse", "url": "https://x/sse", "disabled": true}}}')
        self.assertEqual(result["format"], "json-vscode")
        self.assertEqual(result["servers"]["old"], {"type": "sse", "url": "https://x/sse", "enabled": False})

    def test_bare_entries(self):
        result = importer.parse('{"one": {"command": "npx", "args": ["-y", "pkg"]}}')
        self.assertEqual(result["format"], "json-entries")
        self.assertIn("one", result["servers"])

    def test_invalid_json(self):
        with self.assertRaisesRegex(importer.ImportError_, "Invalid JSON"):
            importer.parse('{"mcpServers": ')


class CodexTomlTest(unittest.TestCase):
    TOML = '''
model = "o4-mini"

[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp"]
cwd = "~/Projects"
env_vars = ["LOCAL_TOKEN"]
startup_timeout_sec = 20
disabled_tools = ["debug"]

[mcp_servers.context7.env]
MY_ENV_VAR = "value"

[mcp_servers.figma]
url = "https://mcp.figma.com/mcp"
bearer_token_env_var = "FIGMA_OAUTH_TOKEN"
http_headers = { "X-Figma-Region" = "us-east-1" }
env_http_headers = { "X-Team" = "FIGMA_TEAM" }
enabled_tools = ["open", "screenshot"]
default_tools_approval_mode = "prompt"
http_headers_helper = "print-headers"
enabled = false

[mcp_servers.figma.tools.open]
approval_mode = "approve"

[mcp_servers.github]
url = "https://api.githubcopilot.com/mcp/"
scopes = ["repo", "read:user"]

[mcp_servers.github.oauth]
client_id = "Iv1.abc"
client_secret = "s3cret"
callback_port = 5555
'''

    def test_maps_codex_entries(self):
        result = importer.parse(self.TOML)
        self.assertEqual(result["format"], "toml-codex")
        self.assertEqual(result["servers"]["context7"], {
            "command": "npx", "args": ["-y", "@upstash/context7-mcp"], "env": {"MY_ENV_VAR": "value"},
            "cwd": "~/Projects", "disabledTools": ["debug"], "enabled": True})
        self.assertEqual(result["servers"]["figma"], {
            "type": "http", "url": "https://mcp.figma.com/mcp", "enabledTools": ["open", "screenshot"], "enabled": False,
            "headers": {"X-Figma-Region": "us-east-1", "X-Team": "${env:FIGMA_TEAM}", "Authorization": "Bearer ${env:FIGMA_OAUTH_TOKEN}"}})
        self.assertEqual(result["servers"]["github"]["oauth"], {"clientId": "Iv1.abc", "clientSecret": "s3cret", "scopes": "repo read:user"})

    def test_reports_what_is_dropped(self):
        found = reasons(importer.parse(self.TOML))
        self.assertIn(("context7", "env_vars", "env-forwarding"), found)
        self.assertIn(("context7", "startup_timeout_sec", "client"), found)
        self.assertIn(("figma", "default_tools_approval_mode", "client"), found)
        self.assertIn(("figma", "tools", "client"), found)
        self.assertIn(("figma", "http_headers_helper", "unsupported"), found)
        self.assertIn(("github", "oauth.callback_port", "unsupported"), found)

    def test_invalid_toml(self):
        with self.assertRaisesRegex(importer.ImportError_, "Invalid TOML"):
            importer.parse('[mcp_servers.x]\ncommand = "npx\n')


class CommandTest(unittest.TestCase):
    def test_claude_mcp_add_variants(self):
        result = importer.parse('''
claude mcp add --transport http carrera https://example.com/mcp --header "Authorization: Bearer TOKEN"
claude mcp add -s user -e API_KEY=abc files -- npx -y @modelcontextprotocol/server-filesystem ~/Docs
claude mcp add --transport=sse legacy https://example.com/sse
claude mcp add-json web '{"command": "uvx", "args": ["mcp-server-fetch"]}'
''')
        self.assertEqual(result["format"], "cli-claude")
        servers = result["servers"]
        self.assertEqual(servers["carrera"], {"type": "http", "url": "https://example.com/mcp", "headers": {"Authorization": "Bearer TOKEN"}, "enabled": True})
        self.assertEqual(servers["files"], {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "~/Docs"], "env": {"API_KEY": "abc"}, "enabled": True})
        self.assertEqual(servers["legacy"]["type"], "sse")
        self.assertEqual(servers["web"]["command"], "uvx")

    def test_codex_mcp_add_variants(self):
        result = importer.parse('''codex mcp add docs --env TOKEN=1 -- docs-server --port 4000
codex mcp add figma --url https://mcp.figma.com/mcp --bearer-token-env-var FIGMA_TOKEN
codex mcp add gh --url https://api.githubcopilot.com/mcp/ --oauth-client-id Iv1.abc''')
        self.assertEqual(result["format"], "cli-codex")
        self.assertEqual(result["servers"]["docs"], {"command": "docs-server", "args": ["--port", "4000"], "env": {"TOKEN": "1"}, "enabled": True})
        self.assertEqual(result["servers"]["figma"]["headers"], {"Authorization": "Bearer ${env:FIGMA_TOKEN}"})
        self.assertEqual(result["servers"]["gh"]["oauth"], {"clientId": "Iv1.abc"})

    def test_line_continuations_and_mixed(self):
        result = importer.parse('claude mcp add a -- uvx one \\\n  --flag\ncodex mcp add b -- two')
        self.assertEqual(result["format"], "cli-mixed")
        self.assertEqual(result["servers"]["a"], {"command": "uvx", "args": ["one", "--flag"], "enabled": True})

    def test_unknown_option_is_an_error(self):
        with self.assertRaisesRegex(importer.ImportError_, "Unsupported option"):
            importer.parse("claude mcp add --weird x y")


class GeneralTest(unittest.TestCase):
    def test_skips_entries_pointing_to_the_hub(self):
        result = importer.parse('''{"mcpServers": {
            "mcp-hub": {"type": "http", "url": "http://127.0.0.1:4747/mcp"},
            "bridge": {"command": "python3", "args": ["bridge.py", "http://localhost:4747/mcp"]},
            "other": {"command": "uvx", "args": ["x"]}}}''', hub_port=4747)
        self.assertEqual(list(result["servers"]), ["other"])
        self.assertEqual({w["server"] for w in result["warnings"] if w["reason"] == "self"}, {"mcp-hub", "bridge"})

    def test_hub_detection_respects_the_port(self):
        self.assertTrue(importer.points_to_hub({"url": "http://127.0.0.1:4747/mcp"}, 4747))
        self.assertFalse(importer.points_to_hub({"url": "http://127.0.0.1:47470/mcp"}, 4747))
        self.assertTrue(importer.points_to_hub({"args": ["bridge.py", "http://localhost:4747/mcp"]}, 4747))

    def test_unrecognized_and_empty(self):
        with self.assertRaisesRegex(importer.ImportError_, "Unrecognized format"):
            importer.parse("hello world")
        with self.assertRaisesRegex(importer.ImportError_, "Nothing to import"):
            importer.parse("   ")


if __name__ == "__main__":
    unittest.main()
