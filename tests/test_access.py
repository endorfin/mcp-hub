import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config_store  # noqa: E402
import hub as hub_module  # noqa: E402

SCHEMA = {"type": "object"}
TOOLS = [
    {"name": "get", "inputSchema": SCHEMA, "annotations": {"readOnlyHint": True}},
    {"name": "put", "inputSchema": SCHEMA, "annotations": {"readOnlyHint": False, "destructiveHint": False}},
    {"name": "drop", "inputSchema": SCHEMA, "annotations": {"destructiveHint": True}},
    {"name": "plain", "inputSchema": SCHEMA},
]


class TierTest(unittest.TestCase):
    def test_tiers_follow_the_spec_defaults(self):
        self.assertEqual([hub_module.tier(t) for t in TOOLS], ["read", "write", "destructive", "unknown"])
        self.assertEqual(hub_module.tier({"annotations": {"readOnlyHint": False}}), "destructive")


class ProfileAccessTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        tools = Path(self.home.name, "tools.json")
        tools.write_text(json.dumps(TOOLS))
        entry = {"command": sys.executable, "args": [str(ROOT / "tests" / "dummy_server.py")],
                 "env": {"DUMMY_TOOLS": str(tools)}}
        self.profiles = {"profiles": {name: {"servers": {"alpha": {"enabled": True, "disabledTools": []}}, "access": name}
                                      for name in ("read", "write")}}
        self.hub = hub_module.Hub(lambda: {"mcpServers": {"alpha": entry}}, lambda: {"passEnvironment": True},
                                  self.home.name, lambda: self.profiles)
        self.hub.sync()

    def tearDown(self):
        self.hub.close()
        self.home.cleanup()

    def names(self, profile=None):
        return sorted(t["name"] for t in self.hub.handle("tools/list", {}, profile=profile)["tools"])

    def test_profiles_see_only_their_tiers(self):
        self.assertEqual(self.names(), ["alpha__drop", "alpha__get", "alpha__plain", "alpha__put"])
        self.assertEqual(self.names("read"), ["alpha__get"])
        self.assertEqual(self.names("write"), ["alpha__get", "alpha__put"])

    def test_calls_above_the_tier_are_rejected(self):
        with self.assertRaisesRegex(hub_module.JsonRpcError, "only allows read-only tools"):
            self.hub.handle("tools/call", {"name": "alpha__put"}, profile="read")
        with self.assertRaisesRegex(hub_module.JsonRpcError, "only allows non-destructive tools"):
            self.hub.handle("tools/call", {"name": "alpha__plain"}, profile="write")

    def test_tool_picker_reports_the_tier(self):
        self.assertEqual({t["name"]: t["tier"] for t in self.hub.tools("alpha")},
                         {"get": "read", "put": "write", "drop": "destructive", "plain": "unknown"})


class ProfileStoreTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config_store, "PROFILES_FILE", Path(self.home.name, "profiles.json"))
        self.patch.start()
        config_store.write_json(config_store.PROFILES_FILE, {"profiles": {"p": {"servers": {}}}})

    def tearDown(self):
        self.patch.stop()
        self.home.cleanup()

    def test_access_is_set_validated_and_cleared(self):
        self.assertIsNone(config_store.update_profiles("access", "p", access="read"))
        self.assertEqual(config_store.load_profiles()["profiles"]["p"]["access"], "read")
        self.assertIn("access must be", config_store.update_profiles("access", "p", access="admin"))
        self.assertIn("Unknown profile", config_store.update_profiles("access", "nope", access="read"))
        config_store.update_profiles("access", "p", access="all")
        self.assertNotIn("access", config_store.load_profiles()["profiles"]["p"])

    def test_updating_a_profile_keeps_its_access(self):
        config_store.update_profiles("access", "p", access="write")
        with mock.patch.object(config_store, "load_config", return_value={"mcpServers": {}}):
            config_store.update_profiles("save", "p")
        self.assertEqual(config_store.load_profiles()["profiles"]["p"]["access"], "write")


if __name__ == "__main__":
    unittest.main()
