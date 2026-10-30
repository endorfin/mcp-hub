#!/usr/bin/env python3
import json
import sys
import threading
import time
import urllib.error
import urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4747/mcp"
USER_AGENT = "mcp-hub-bridge/1.0"

out_lock = threading.Lock()
session_lock = threading.Lock()
session = {"id": None, "version": None, "init": None, "generation": 0}


class SessionGone(Exception):
    pass


def write(message):
    with out_lock:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()


def log(text):
    sys.stderr.write(f"mcp-hub-bridge: {text}\n")
    sys.stderr.flush()


def headers(extra=None):
    result = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
              "User-Agent": USER_AGENT, **(extra or {})}
    if session["id"]:
        result["Mcp-Session-Id"] = session["id"]
    if session["version"]:
        result["MCP-Protocol-Version"] = session["version"]
    return result


def post(message):
    request = urllib.request.Request(URL, json.dumps(message).encode(), headers(), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=330) as response:
            body = response.read()
            new_id = response.headers.get("Mcp-Session-Id")
            if not body:
                return None, new_id
            if "text/event-stream" in response.headers.get("Content-Type", ""):
                lines = [line[5:].strip() for line in body.decode().splitlines() if line.startswith("data:")]
                return [json.loads(line) for line in lines], new_id
            return json.loads(body), new_id
    except urllib.error.HTTPError as e:
        with e:
            if e.code == 404 and session["id"]:
                raise SessionGone()
            raise


def initialize():
    session["id"] = None
    reply, new_id = post({"jsonrpc": "2.0", "id": "bridge-init", "method": "initialize", "params": session["init"]})
    session["id"] = new_id
    session["version"] = (reply or {}).get("result", {}).get("protocolVersion")
    session["generation"] += 1
    post({"jsonrpc": "2.0", "method": "notifications/initialized"})


def reinitialize(stale_generation):
    with session_lock:
        if session["generation"] != stale_generation:
            return
        log("Session expired, signing in again")
        initialize()
        threading.Thread(target=listen, args=(session["generation"],), daemon=True).start()
    for kind in ("tools", "prompts", "resources"):
        write({"jsonrpc": "2.0", "method": f"notifications/{kind}/list_changed"})


def forward(message):
    for attempt in range(2):
        generation = session["generation"]
        try:
            reply, new_id = post(message)
            if message.get("method") == "initialize" and new_id:
                session["id"] = new_id
                session["version"] = (reply or {}).get("result", {}).get("protocolVersion")
                session["generation"] += 1
                threading.Thread(target=listen, args=(session["generation"],), daemon=True).start()
            for item in reply if isinstance(reply, list) else [reply] if reply else []:
                write(item)
            return
        except SessionGone:
            if attempt or not session["init"]:
                break
            try:
                reinitialize(generation)
            except (OSError, ValueError) as e:
                log(f"Re-initialization failed: {e}")
                break
        except (OSError, ValueError) as e:
            if "id" in message:
                write({"jsonrpc": "2.0", "id": message["id"],
                       "error": {"code": -32000, "message": f"MCP Hub not reachable ({URL}): {e}"}})
            return
    if "id" in message:
        write({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32000, "message": "Session with the MCP Hub expired"}})


def listen(generation):
    delay = 1
    while session["generation"] == generation:
        request = urllib.request.Request(URL, headers=headers({"Accept": "text/event-stream"}))
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                delay = 1
                for raw in response:
                    if session["generation"] != generation:
                        return
                    line = raw.decode(errors="replace").strip()
                    if line.startswith("data:"):
                        write(json.loads(line[5:]))
        except urllib.error.HTTPError as e:
            with e:
                if e.code == 404 and session["init"]:
                    try:
                        reinitialize(generation)
                        return
                    except (OSError, ValueError) as error:
                        log(f"Re-initialization failed: {error}")
                elif e.code == 405:
                    return
        except (OSError, ValueError):
            pass
        time.sleep(delay)
        delay = min(delay * 2, 30)


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            log(f"Invalid JSON on stdin: {line[:200]}")
            continue
        if message.get("method") == "initialize":
            session["init"] = message.get("params")
            forward(message)
        else:
            threading.Thread(target=forward, args=(message,), daemon=True).start()


if __name__ == "__main__":
    main()
