import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hub as hub_module  # noqa: E402
import leaks  # noqa: E402

GITHUB = "ghp_" + "a1B2c3D4" * 5
SECRET = "plain-text-secret-123"


class PatternTest(unittest.TestCase):
    def test_known_formats_are_redacted(self):
        samples = {
            "private-key": "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaA\n-----END OPENSSH PRIVATE KEY-----",
            "aws-key": "AKIAIOSFODNN7EXAMPLE",
            "github-token": GITHUB,
            "slack-token": "xoxb-1234567890-abcdefghij",
            "stripe-key": "sk_live_" + "x" * 24,
            "anthropic-key": "sk-ant-api03-" + "y" * 30,
            "openai-key": "sk-proj-" + "z" * 40,
            "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.SflKxwRJSMeKKF2QT4fwpMeJf36P",
        }
        for kind, sample in samples.items():
            text, kinds = leaks.redact(f"value: {sample} end")
            self.assertEqual((text, kinds), (f"value: [redacted:{kind}] end", [kind]), kind)

    def test_only_the_password_of_a_url_is_redacted(self):
        text, kinds = leaks.redact("postgres://app:hunter22@db.local/app")
        self.assertEqual((text, kinds), ("postgres://app:[redacted:url-password]@db.local/app", ["url-password"]))

    def test_known_values_win_over_patterns(self):
        text, kinds = leaks.redact(f"token {GITHUB}", {GITHUB})
        self.assertEqual((text, kinds), ("token [redacted:hub-secret]", ["hub-secret"]))

    def test_ordinary_text_passes(self):
        for text in ("commit 3f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a3f", "id 550e8400-e29b-41d4-a716-446655440000",
                     "https://example.com/path?x=1", "task-sk-backlog and the skeleton", "ssh://git@github.com/x/y"):
            self.assertEqual(leaks.redact(text), (text, []), text)

    def test_nested_values_are_walked(self):
        value, kinds = leaks.redact_value({"content": [{"type": "text", "text": f"x {GITHUB}"}], "n": 3})
        self.assertEqual((value["content"][0]["text"], value["n"], kinds), ("x [redacted:github-token]", 3, ["github-token"]))


class EntrySecretsTest(unittest.TestCase):
    def test_headers_secret_env_and_references_count_paths_do_not(self):
        with mock.patch.dict(os.environ, {"LEAK_TEST_REF": "from-the-environment"}):
            entry = {"headers": {"Authorization": "Bearer abcdefgh12345"},
                     "env": {"API_TOKEN": "tok-1234567890", "PATH": "/usr/local/bin:/usr/bin", "OTHER": "${env:LEAK_TEST_REF}",
                             "SHORT_KEY": "abc"}}
            self.assertEqual(leaks.entry_secrets(entry, {"Authorization": "Bearer oauth-token-xyz"}),
                             {"abcdefgh12345", "tok-1234567890", "from-the-environment", "oauth-token-xyz"})


class HubLeakTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.entry = {"command": sys.executable, "args": [str(ROOT / "tests" / "dummy_server.py")],
                      "env": {"DUMMY_SECRET": SECRET}}
        self.hub = hub_module.Hub(lambda: {"mcpServers": {"alpha": self.entry}}, lambda: {"passEnvironment": True},
                                  self.home.name)
        self.hub.sync()

    def tearDown(self):
        self.hub.close()
        self.home.cleanup()

    def call(self, tool, **args):
        return self.hub.handle("tools/call", {"name": f"alpha__{tool}", "arguments": args})["content"][0]["text"]

    def test_hub_secret_is_marked_and_masked_in_the_log(self):
        self.assertEqual(self.call("secret"), SECRET)
        [last] = self.hub.calls.recent(1)
        self.assertEqual((last["result"], last["leaks"]), ("[redacted:hub-secret]", [{"kind": "hub-secret", "where": "result"}]))
        self.assertNotIn(SECRET, Path(self.home.name, "calls.jsonl").read_text())
        self.assertEqual(self.hub.calls.stats()["leaks"], 1)

    def test_redact_mode_hides_the_secret_from_the_client(self):
        self.entry["redactSecrets"] = True
        self.assertEqual(self.call("secret"), "[redacted:hub-secret]")
        self.assertTrue(self.hub.calls.recent(1)[0]["redacted"])

    def test_arguments_are_marked_and_masked_but_still_sent(self):
        self.assertEqual(self.call("echo", text=GITHUB), GITHUB)
        [last] = self.hub.calls.recent(1)
        self.assertEqual({(f["kind"], f["where"]) for f in last["leaks"]}, {("github-token", "args"), ("github-token", "result")})
        self.assertNotIn(GITHUB, json.dumps(last))


class RuntimeKeyTest(unittest.TestCase):
    def test_switching_redaction_does_not_restart(self):
        entry = {"command": "x"}
        self.assertEqual(hub_module.runtime_key(entry, True), hub_module.runtime_key({**entry, "redactSecrets": True}, True))


class StoredLogTest(unittest.TestCase):
    def test_existing_entries_are_masked_on_load(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home, "calls.jsonl")
            path.write_text(json.dumps({"t": 1, "server": "a", "target": "x", "args": f'{{"t": "{GITHUB}"}}', "result": "ok"}) + "\n")
            log = hub_module.CallLog(path)
            self.assertIn("[redacted:github-token]", log.recent(1)[0]["args"])
            self.assertNotIn(GITHUB, path.read_text())


if __name__ == "__main__":
    unittest.main()
