import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compact


def tool(name, description, params=(), title=""):
    return {"name": name, "title": title, "description": description,
            "inputSchema": {"type": "object", "properties": {p: {"type": "string"} for p in params}}}


TOOLS = [
    tool("grafana__query_loki_logs", "Executes a LogQL query against a Loki datasource", ["logql"]),
    tool("grafana__search_dashboards", "Search Grafana dashboards by query"),
    tool("prun__restart", "Stop and start a project or a whole group", ["name"]),
    tool("openbrain__search_thoughts", "Search your brain for thoughts related to a query"),
    tool("nuxt__list_deploy_providers", "Lists providers. WHEN TO USE: when my app needs hosting"),
]


def names(found):
    return [t["name"] for t in found]


class SearchTest(unittest.TestCase):
    def test_name_and_server_words_rank_first(self):
        self.assertEqual(names(compact.search(TOOLS, "loki logs", limit=1)), ["grafana__query_loki_logs"])
        self.assertEqual(names(compact.search(TOOLS, "restart prun", limit=1)), ["prun__restart"])

    def test_prefixes_and_camel_case_match(self):
        self.assertEqual(names(compact.search(TOOLS, "dashboard", limit=1)), ["grafana__search_dashboards"])
        self.assertEqual(compact.words("getWorklogs list_items"), ["get", "worklogs", "list", "items"])

    def test_stopwords_do_not_count_and_server_descriptions_help(self):
        found = compact.search(TOOLS, "search my notes", about={"openbrain": "Gedanken und notes speichern"})
        self.assertEqual(names(found)[0], "openbrain__search_thoughts")
        self.assertNotIn("nuxt__list_deploy_providers", names(found))

    def test_server_filter_and_empty_query(self):
        self.assertEqual(names(compact.search(TOOLS, "", server="grafana")), ["grafana__query_loki_logs", "grafana__search_dashboards"])
        self.assertEqual(compact.search(TOOLS, ""), [])
        self.assertEqual(len(compact.search(TOOLS * 10, "query", limit=99)), 25)


class OutputTest(unittest.TestCase):
    def test_results_are_short_lines(self):
        text = compact.format_results([tool("a__b", "x" * 400)])
        self.assertTrue(text.startswith("a__b: x"))
        self.assertLess(len(text), 180)
        self.assertIn("No matching tools", compact.format_results([]))

    def test_meta_tools_name_the_servers(self):
        tools = compact.meta_tools(["alpha", "beta"])
        self.assertEqual([t["name"] for t in tools], ["search_tools", "describe_tool", "call_tool"])
        self.assertIn("Servers: alpha, beta.", tools[0]["description"])


if __name__ == "__main__":
    unittest.main()
