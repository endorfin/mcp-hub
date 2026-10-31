import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hub as hub_module  # noqa: E402


class ResponseSizeTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.home.cleanup()

    def test_stats_report_sizes_per_server_and_the_largest_tools(self):
        log = hub_module.CallLog(Path(self.home.name, "calls.jsonl"))
        now = time.time()
        for server, tool, size in (("a", "big", 9000), ("a", "big", 11000), ("a", "small", 100), ("b", "x", 500)):
            log.record({"t": now, "client": "c", "server": server, "target": tool, "ok": True, "ms": 5, "size": size})
        log.record({"t": now, "client": "c", "server": "b", "target": "old", "ok": True, "ms": 5})
        stats = log.stats()
        self.assertEqual((stats["volume"], stats["medianSize"]), (20600, 4750))
        a = next(s for s in stats["servers"] if s["server"] == "a")
        self.assertEqual((a["size"], a["volume"]), (9000, 20100))
        self.assertEqual([(t["tool"], t["size"]) for t in stats["largest"]], [("big", 10000), ("x", 500), ("small", 100)])

    def test_forwarded_calls_record_the_response_size(self):
        entry = {"command": sys.executable, "args": [str(ROOT / "tests" / "dummy_server.py")]}
        hub = hub_module.Hub(lambda: {"mcpServers": {"alpha": entry}}, lambda: {"passEnvironment": True}, self.home.name)
        try:
            hub.sync()
            result = hub.handle("tools/call", {"name": "alpha__echo", "arguments": {"text": "x" * 1000}})
            [last] = hub.calls.recent(1)
            self.assertEqual(last["size"], len(json.dumps(result, ensure_ascii=False).encode()))
            self.assertGreater(last["size"], 1000)
        finally:
            hub.close()


if __name__ == "__main__":
    unittest.main()
