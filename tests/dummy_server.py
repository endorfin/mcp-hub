import json
import os
import sys

TOOLS = [
    {"name": "echo", "description": "Returns the text", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
    {"name": "secret", "description": "Returns DUMMY_SECRET", "inputSchema": {"type": "object"}},
    {"name": "fail", "description": "Always fails", "inputSchema": {"type": "object"}},
]


def reply(message_id, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": message_id}
    message["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def text(value):
    return {"content": [{"type": "text", "text": value}]}


for line in sys.stdin:
    message = json.loads(line)
    method, message_id = message.get("method"), message.get("id")
    if message_id is None:
        continue
    params = message.get("params") or {}
    if method == "initialize":
        reply(message_id, {"protocolVersion": params.get("protocolVersion"), "capabilities": {"tools": {}},
                           "serverInfo": {"name": "dummy", "version": "1"}})
    elif method == "tools/list":
        reply(message_id, {"tools": TOOLS})
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name == "echo":
            reply(message_id, text(args.get("text", "")))
        elif name == "secret":
            reply(message_id, text(os.environ.get("DUMMY_SECRET", "")))
        else:
            reply(message_id, error={"code": -32000, "message": "failed on purpose"})
    elif method == "ping":
        reply(message_id, {})
    else:
        reply(message_id, error={"code": -32601, "message": f"unknown: {method}"})
