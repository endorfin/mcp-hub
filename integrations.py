import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import importer

NAME = "mcp-hub"
KEEP_BACKUPS = 5


class IntegrationError(Exception):
    pass


def _locations():
    override = os.environ.get("MCP_HUB_CLIENT_HOME")
    home = Path(override) if override else Path.home()
    if sys.platform == "darwin":
        support = home / "Library" / "Application Support"
    elif sys.platform == "win32":
        support = home / "AppData" / "Roaming" if override else Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    else:
        support = home / ".config" if override else Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    codex = home / ".codex" if override else Path(os.environ.get("CODEX_HOME") or home / ".codex")
    return home, support, codex


def clients():
    home, support, codex = _locations()
    return [
        {"id": "claude-code", "name": "Claude Code", "kind": "cli", "path": home / ".claude.json", "key": "mcpServers"},
        {"id": "claude-desktop", "name": "Claude Desktop", "kind": "json", "path": support / "Claude" / "claude_desktop_config.json",
         "key": "mcpServers", "bridge": True, "restart": True},
        {"id": "codex", "name": "Codex", "kind": "toml", "path": codex / "config.toml"},
        {"id": "cursor", "name": "Cursor", "kind": "json", "path": home / ".cursor" / "mcp.json", "key": "mcpServers"},
        {"id": "vscode", "name": "VS Code", "kind": "json", "path": support / "Code" / "User" / "mcp.json", "key": "servers",
         "typed": True},
        {"id": "copilot", "name": "Copilot CLI", "kind": "json", "path": home / ".copilot" / "mcp-config.json",
         "key": "mcpServers", "typed": True, "tools": True},
    ]


def _find(client_id):
    client = next((c for c in clients() if c["id"] == client_id), None)
    if not client:
        raise IntegrationError(f"Unknown client: {client_id}")
    return client


def _read_json(path):
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise IntegrationError(f"{path.name} is not plain JSON (comments?) – edit it by hand: {e}")
    if not isinstance(data, dict):
        raise IntegrationError(f"{path.name} does not contain a JSON object")
    return data


def _servers(client):
    if client["kind"] == "toml":
        try:
            data = tomllib.loads(client["path"].read_text())
        except FileNotFoundError:
            return {}
        except tomllib.TOMLDecodeError as e:
            raise IntegrationError(f"{client['path'].name} is not valid TOML: {e}")
        return data.get("mcp_servers") or {}
    servers = _read_json(client["path"]).get(client["key"]) or {}
    return servers if isinstance(servers, dict) else {}


def _points_to_hub(entry, port):
    return isinstance(entry, dict) and importer._points_to_hub(
        {"url": entry.get("url") or entry.get("serverUrl") or "", "args": [str(a) for a in entry.get("args") or []]}, port)


def _hub_names(servers, port):
    return [name for name, entry in servers.items() if _points_to_hub(entry, port)]


def status(port):
    rows = []
    for client in clients():
        home = str(_locations()[0])
        path = str(client["path"])
        row = {"id": client["id"], "name": client["name"], "path": path, "restart": bool(client.get("restart")),
               "display": "~" + path[len(home):] if path.startswith(home) else path}
        installed = client["path"].exists() or client["path"].parent.exists()
        if client["kind"] == "cli":
            installed = installed and shutil.which("claude") is not None
        row["installed"] = installed
        try:
            servers = _servers(client)
            hub = _hub_names(servers, port)
            row["connected"] = bool(hub)
            row["compact"] = any("/mcp/compact" in json.dumps(servers[name]) for name in hub)
            row["importable"] = sorted(name for name in servers if name not in hub)
        except IntegrationError as e:
            row.update(connected=False, compact=False, importable=[], error=str(e))
        rows.append(row)
    return rows


def _backup(path):
    if not path.exists():
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target, n = path.with_name(f"{path.name}.mcp-hub-{stamp}.bak"), 1
    while target.exists():
        n += 1
        target = path.with_name(f"{path.name}.mcp-hub-{stamp}-{n}.bak")
    shutil.copy2(path, target)
    backups = sorted(path.parent.glob(f"{path.name}.mcp-hub-*.bak"), key=lambda p: p.stat().st_mtime_ns)
    for old in backups[:-KEEP_BACKUPS]:
        old.unlink()


def _write_json(path, data):
    _backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".mcp-hub.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def _hub_entry(client, url, bridge):
    if client.get("bridge"):
        return {"command": bridge["python"], "args": [bridge["script"], url]}
    entry = {"type": "http", "url": url} if client.get("typed") else {"url": url}
    if client.get("tools"):
        entry["tools"] = ["*"]
    return entry


def _claude(*args):
    executable = shutil.which("claude")
    if not executable:
        raise IntegrationError("claude CLI not found")
    done = subprocess.run([executable, "mcp", *args], capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise IntegrationError(f"claude mcp {args[0]} failed: {(done.stderr or done.stdout).strip()}")


TABLE = re.compile(r"^\s*\[\s*([^\[\]]+?)\s*\]\s*(?:#.*)?$")


def _table_server(header):
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"|\'([^\']*)\'|([A-Za-z0-9_-]+)', header)
    keys = [a or b or c for a, b, c in parts]
    return keys[1] if len(keys) >= 2 and keys[0] == "mcp_servers" else None


def toml_server_sections(text, exclude):
    out, keep = [], False
    for line in text.splitlines(keepends=True):
        match = TABLE.match(line)
        if match:
            server = _table_server(match.group(1))
            keep = server is not None and server not in exclude
        if keep:
            out.append(line)
    result = "".join(out)
    servers = tomllib.loads(text).get("mcp_servers") or {}
    expected = {k: v for k, v in servers.items() if k not in exclude}
    return result if (tomllib.loads(result).get("mcp_servers") or {}) == expected else None


def remove_toml_servers(text, names):
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        match = TABLE.match(line)
        if match:
            skipping = _table_server(match.group(1)) in names
        if not skipping:
            out.append(line)
    result = "".join(out)
    before = tomllib.loads(text).get("mcp_servers") or {}
    after = tomllib.loads(result).get("mcp_servers") or {}
    expected = {k: v for k, v in before.items() if k not in names}
    if after != expected:
        raise IntegrationError("Could not remove the entries from config.toml cleanly – edit it by hand")
    return result


def _write_toml(path, text):
    _backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".mcp-hub.tmp")
    tmp.write_text(text)
    tmp.replace(path)


def connect(client_id, url, port, bridge):
    client = _find(client_id)
    servers = _servers(client)
    stale = _hub_names(servers, port)
    if client["kind"] == "cli":
        for name in stale:
            _claude("remove", "--scope", "user", name)
        _claude("add", "--scope", "user", "--transport", "http", NAME, url)
        return
    if client["kind"] == "toml":
        path = client["path"]
        text = path.read_text() if path.exists() else ""
        text = remove_toml_servers(text, set(stale) | {NAME}) if text.strip() else ""
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + f'[mcp_servers.{NAME}]\nurl = {json.dumps(url)}\n'
        if (tomllib.loads(text).get("mcp_servers") or {}).get(NAME, {}).get("url") != url:
            raise IntegrationError("Could not add the hub to config.toml cleanly – edit it by hand")
        _write_toml(path, text)
        return
    data = _read_json(client["path"])
    entries = data.get(client["key"]) if isinstance(data.get(client["key"]), dict) else {}
    entries = {name: entry for name, entry in entries.items() if name not in stale}
    entries[NAME] = _hub_entry(client, url, bridge)
    data[client["key"]] = entries
    _write_json(client["path"], data)


def disconnect(client_id, port):
    remove(client_id, _hub_names(_servers(_find(client_id)), port))


def remove(client_id, names):
    client = _find(client_id)
    names = set(names)
    if not names:
        return
    if client["kind"] == "cli":
        for name in names:
            _claude("remove", "--scope", "user", name)
        return
    if client["kind"] == "toml":
        _write_toml(client["path"], remove_toml_servers(client["path"].read_text(), names))
        return
    data = _read_json(client["path"])
    entries = data.get(client["key"]) or {}
    data[client["key"]] = {name: entry for name, entry in entries.items() if name not in names}
    _write_json(client["path"], data)


def export(client_id, port):
    client = _find(client_id)
    servers = _servers(client)
    hub = _hub_names(servers, port)
    names = sorted(name for name in servers if name not in hub)
    if client["kind"] == "toml":
        text = client["path"].read_text()
        sections = toml_server_sections(text, set(hub))
        return {"text": sections if sections is not None else remove_toml_servers(text, set(hub)), "servers": names}
    key = "servers" if client["key"] == "servers" else "mcpServers"
    return {"text": json.dumps({key: {name: servers[name] for name in names}}, indent=2, ensure_ascii=False), "servers": names}
