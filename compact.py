import json
import math
import re

SEARCH, DESCRIBE, CALL = "search_tools", "describe_tool", "call_tool"
WEIGHTS = {"name": 3.0, "server": 2.0, "title": 2.0, "params": 1.0, "description": 1.0, "about": 0.5}
STOPWORDS = set("a an and are as at be by for from how i in is it my of on or that the this to use with "
                "alle am an auf aus bei das dem den der des die ein eine einen für im in ist mein meine meinen mit "
                "nach oder von vom zu zum zur und".split())


def words(text):
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text or "")
    return re.findall(r"[a-z0-9]+", text.lower())


def meta_tools(servers):
    listing = ", ".join(servers) or "none"
    return [
        {
            "name": SEARCH,
            "title": "Search tools",
            "description": "Find tools of the bundled MCP servers by what you want to do. Returns matching tool names "
                           f"with a short description. Servers: {listing}.",
            "inputSchema": {"type": "object", "properties": {
                "query": {"type": "string", "description": "What the tool should do, in a few words"},
                "server": {"type": "string", "description": "Only search the tools of this server"},
                "limit": {"type": "integer", "description": "Maximum number of results (default 8, at most 25)"},
            }},
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": DESCRIBE,
            "title": "Describe tool",
            "description": "Full description and input schema of a tool found with search_tools.",
            "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": CALL,
            "title": "Call tool",
            "description": "Call a tool found with search_tools, with arguments that match its input schema.",
            "inputSchema": {"type": "object", "properties": {
                "name": {"type": "string"},
                "arguments": {"type": "object"},
            }, "required": ["name"]},
        },
    ]


def instructions(servers, tool_count):
    lines = [f"This hub bundles {len(servers)} MCP servers with {tool_count} tools. They are not listed one by one: "
             f"call {SEARCH} with what you want to do, {DESCRIBE} for the input schema, then {CALL}."]
    lines += [f"- {name}: {summary}" if summary else f"- {name}" for name, summary in servers.items()]
    return "\n".join(lines)


def search(tools, query, server=None, limit=8, about=None):
    limit = max(1, min(int(limit or 8), 25))
    if server:
        tools = [t for t in tools if t["name"].startswith(server + "__")]
    fields = []
    for tool in tools:
        params = (tool.get("inputSchema") or {}).get("properties") or {}
        fields.append({
            "name": set(words(tool["name"].split("__", 1)[-1])),
            "server": set(words(tool["name"].split("__", 1)[0])),
            "title": set(words(tool.get("title", "").split(": ", 1)[-1])),
            "params": set(words(" ".join(params))),
            "description": set(words(tool.get("description"))),
            "about": set(words((about or {}).get(tool["name"].split("__", 1)[0], ""))),
        })
    terms = [term for term in dict.fromkeys(words(query)) if term not in STOPWORDS]
    if not terms:
        return tools[:limit] if server else []
    df = {term: sum(any(_hit(term, f[k]) for k in f) for f in fields) for term in terms}
    scored = []
    for tool, f in zip(tools, fields):
        score = 0.0
        for term in terms:
            idf = math.log(1 + len(tools) / (1 + df[term]))
            score += idf * max((WEIGHTS[k] * _hit(term, f[k]) for k in f), default=0)
        if score:
            scored.append((score, tool))
    scored.sort(key=lambda pair: -pair[0])
    return [tool for _, tool in scored[:limit]]


def _hit(term, vocabulary):
    if term in vocabulary:
        return 1.0
    if len(term) >= 3 and any(word.startswith(term) or (len(word) >= 4 and term.startswith(word)) for word in vocabulary):
        return 0.6
    return 0.0


def format_results(found):
    if not found:
        return "No matching tools. Try other words, or pass a server to list its tools."
    lines = []
    for tool in found:
        description = " ".join((tool.get("description") or "").split())
        if len(description) > 160:
            description = description[:157] + "…"
        lines.append(f"{tool['name']}: {description}" if description else tool["name"])
    return "\n".join(lines)


def describe(tool):
    return json.dumps({k: tool[k] for k in ("name", "title", "description", "inputSchema") if k in tool},
                      ensure_ascii=False, indent=1)


def text(value, error=False):
    return {"content": [{"type": "text", "text": value}], **({"isError": True} if error else {})}
