import json
import os
import shutil
import sys
import threading
from pathlib import Path

import hub as hub_module
from fsutil import atomic_write

lock = threading.RLock()
DEFAULT_HOME = Path(os.environ["APPDATA"]) / "mcp-hub" if sys.platform == "win32" and os.environ.get("APPDATA") \
    else Path.home() / ".config" / "mcp-hub"
STATE_DIR = Path(os.environ.get("MCP_HUB_HOME") or DEFAULT_HOME)
SETTINGS_FILE = STATE_DIR / "gui-settings.json"
PROFILES_FILE = STATE_DIR / "profiles.json"

DEFAULT_SETTINGS = {
    "configPath": str(STATE_DIR / "servers.json"),
    "passEnvironment": True,
    "language": "auto",
    "checkUpdates": True,
}
def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def write_json(path, data):
    path = Path(path).expanduser()
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def load_settings():
    stored = read_json(SETTINGS_FILE, {})
    return {k: stored.get(k, v) for k, v in DEFAULT_SETTINGS.items()}


def config_path():
    return Path(load_settings()["configPath"]).expanduser()


def load_config():
    data = read_json(config_path(), {"mcpServers": {}})
    data.setdefault("mcpServers", {})
    return data


def validate_servers(servers):
    if not isinstance(servers, dict):
        return "mcpServers must be an object"
    for name, entry in servers.items():
        if not name or "/" in name or name.strip() != name:
            return f"Invalid name: {name!r}"
        if not isinstance(entry, dict):
            return f"{name}: entry must be an object"
        if not entry.get("command") and not entry.get("url"):
            return f"{name}: command or url is missing"
        if not isinstance(entry.get("headers", {}), dict):
            return f"{name}: headers must be an object"
        if not isinstance(entry.get("args", []), list):
            return f"{name}: args must be a list"
        if not isinstance(entry.get("oauth", {}), dict):
            return f"{name}: oauth must be an object"
        if not isinstance(entry.get("cwd", ""), str):
            return f"{name}: cwd must be a string"
        if not isinstance(entry.get("enabledTools", []), list):
            return f"{name}: enabledTools must be a list"
        if not isinstance(entry.get("disabledTools", []), list):
            return f"{name}: disabledTools must be a list"
        if not isinstance(entry.get("env", {}), dict):
            return f"{name}: env must be an object"
        for key in ("args", "env", "headers"):
            values = entry.get(key) or ([] if key == "args" else {})
            if not all(isinstance(v, str) for v in (values if key == "args" else values.values())):
                return f"{name}: values in {key} must be strings"
    prefixes = {}
    for name in servers:
        prefix = hub_module.prefix_of(name)
        if prefix in prefixes:
            return f"{prefixes[prefix]} and {name} would share the tool prefix {prefix}"
        prefixes[prefix] = name
    return None


def load_profiles():
    data = read_json(PROFILES_FILE, {})
    return {"active": data.get("active"), "profiles": data.get("profiles") or {}}


def profile_snapshot(servers):
    return {name: {"enabled": entry.get("enabled", True), "disabledTools": sorted(entry.get("disabledTools") or [])}
            for name, entry in servers.items()}


def save_servers(servers):
    with lock:
        config = load_config()
        config["mcpServers"] = servers
        write_json(config_path(), config)


def save_settings(data):
    with lock:
        write_json(SETTINGS_FILE, {k: data.get(k, v) for k, v in load_settings().items()})


def update_profiles(action, name, new_name=None, on_config_change=lambda: None):
    with lock:
        return _update_profiles(action, name, new_name, on_config_change)


def _update_profiles(action, name, new_name, on_config_change):
    data = load_profiles()
    profiles = data["profiles"]
    if action == "clear":
        config = load_config()
        for entry in config["mcpServers"].values():
            entry["enabled"] = True
            entry.pop("disabledTools", None)
        write_json(config_path(), config)
        on_config_change()
        data["active"] = None
    elif not name or not name.strip() or "/" in name:
        return "Profile name is missing or contains “/”"
    elif action == "save":
        profiles[name] = {"servers": profile_snapshot(load_config()["mcpServers"])}
        data["active"] = name
    elif action == "apply":
        if name not in profiles:
            return f"Unknown profile: {name}"
        config = load_config()
        for server, wanted in profiles[name]["servers"].items():
            entry = config["mcpServers"].get(server)
            if entry is None:
                continue
            entry["enabled"] = wanted["enabled"]
            if wanted["disabledTools"]:
                entry["disabledTools"] = wanted["disabledTools"]
            else:
                entry.pop("disabledTools", None)
        write_json(config_path(), config)
        on_config_change()
        data["active"] = name
    elif action == "rename":
        new_name = (new_name or "").strip()
        if name not in profiles:
            return f"Unknown profile: {name}"
        if not new_name or "/" in new_name:
            return "Invalid new name"
        if new_name != name and new_name in profiles:
            return f"Profile “{new_name}” already exists"
        profiles[new_name] = profiles.pop(name)
        if data["active"] == name:
            data["active"] = new_name
    elif action == "delete":
        profiles.pop(name, None)
        if data["active"] == name:
            data["active"] = None
    else:
        return f"Unknown action: {action}"
    write_json(PROFILES_FILE, data)
    return None
