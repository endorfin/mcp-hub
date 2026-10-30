import json
import re
import shlex
import tomllib

ENTRY_KEYS = {"command", "args", "env", "cwd", "url", "type", "headers", "description", "enabled",
              "disabledTools", "enabledTools", "oauth"}
JSON_CLIENT_KEYS = {"tools", "autoApprove", "alwaysAllow", "timeout", "trust", "gallery", "version", "envFile"}
CODEX_CLIENT_KEYS = {"required", "default_tools_approval_mode", "tools", "startup_timeout_sec", "tool_timeout_sec"}
CODEX_UNSUPPORTED = {"http_headers_helper", "experimental_environment", "callback_port", "callback_url"}


class ImportError_(ValueError):
    pass


def _transport(entry):
    kind = (entry.get("type") or entry.get("transport") or "").lower().replace("_", "-")
    if kind == "sse":
        return "sse"
    if kind in ("http", "streamable-http", "streamablehttp") or (entry.get("url") and not entry.get("command")):
        return "http"
    return "stdio"


def _from_json_entry(name, raw, warnings):
    entry = {}
    if raw.get("command"):
        entry["command"] = raw["command"]
        entry["args"] = [str(a) for a in raw.get("args") or []]
        for key in ("env", "cwd"):
            if raw.get(key):
                entry[key] = raw[key]
    elif raw.get("url") or raw.get("serverUrl"):
        entry["type"] = _transport(raw)
        entry["url"] = raw.get("url") or raw["serverUrl"]
        if raw.get("headers"):
            entry["headers"] = raw["headers"]
    else:
        raise ImportError_(f"{name}: command or url is missing")
    for key in ("description", "disabledTools", "enabledTools", "oauth"):
        if raw.get(key):
            entry[key] = raw[key]
    entry["enabled"] = raw.get("enabled", not raw.get("disabled", False)) is not False
    for key in sorted(set(raw) - ENTRY_KEYS - {"serverUrl", "disabled", "transport"}):
        warnings.append({"server": name, "key": key, "reason": "client" if key in JSON_CLIENT_KEYS else "unsupported"})
    return entry


def _parse_json(text):
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ImportError_("JSON must be an object")
    if isinstance(data.get("mcpServers"), dict):
        source, label = data["mcpServers"], "json-mcpservers"
    elif isinstance(data.get("servers"), dict):
        source, label = data["servers"], "json-vscode"
    elif isinstance(data.get("mcp"), dict) and isinstance(data["mcp"].get("servers"), dict):
        source, label = data["mcp"]["servers"], "json-vscode"
    else:
        source, label = data, "json-entries"
    servers, warnings, skipped = {}, [], []
    for name, raw in source.items():
        if not isinstance(raw, dict) or not (raw.get("command") or raw.get("url") or raw.get("serverUrl")):
            skipped.append(name)
            continue
        servers[name] = _from_json_entry(name, raw, warnings)
    return label, servers, warnings, skipped


def _env_ref(name):
    return "${env:" + name + "}"


def _from_codex_entry(name, raw, warnings):
    entry = {}
    if raw.get("command"):
        entry["command"] = raw["command"]
        entry["args"] = [str(a) for a in raw.get("args") or []]
        if raw.get("env"):
            entry["env"] = {k: str(v) for k, v in raw["env"].items()}
        if raw.get("cwd"):
            entry["cwd"] = raw["cwd"]
        if raw.get("env_vars"):
            warnings.append({"server": name, "key": "env_vars", "reason": "env-forwarding"})
    elif raw.get("url"):
        entry["type"] = "http"
        entry["url"] = raw["url"]
        headers = {k: str(v) for k, v in (raw.get("http_headers") or {}).items()}
        headers.update({k: _env_ref(v) for k, v in (raw.get("env_http_headers") or {}).items()})
        if raw.get("bearer_token_env_var"):
            headers["Authorization"] = "Bearer " + _env_ref(raw["bearer_token_env_var"])
        if headers:
            entry["headers"] = headers
        oauth = raw.get("oauth") or {}
        settings = {"clientId": oauth.get("client_id"), "clientSecret": oauth.get("client_secret")}
        scopes = oauth.get("scopes") or raw.get("scopes")
        if scopes:
            settings["scopes"] = " ".join(scopes) if isinstance(scopes, list) else str(scopes)
        settings = {k: v for k, v in settings.items() if v}
        if settings:
            entry["oauth"] = settings
        for key in sorted(set(oauth) - {"client_id", "client_secret", "scopes"}):
            warnings.append({"server": name, "key": f"oauth.{key}", "reason": "unsupported"})
        if raw.get("auth") == "chatgpt":
            warnings.append({"server": name, "key": "auth", "reason": "client"})
    else:
        raise ImportError_(f"{name}: command or url is missing")
    if raw.get("enabled_tools"):
        entry["enabledTools"] = list(raw["enabled_tools"])
    if raw.get("disabled_tools"):
        entry["disabledTools"] = list(raw["disabled_tools"])
    entry["enabled"] = raw.get("enabled", True) is not False
    known = {"command", "args", "env", "cwd", "env_vars", "url", "http_headers", "env_http_headers",
             "bearer_token_env_var", "oauth", "scopes", "auth", "enabled", "enabled_tools", "disabled_tools"}
    for key in sorted(set(raw) - known):
        warnings.append({"server": name, "key": key, "reason": "client" if key in CODEX_CLIENT_KEYS else "unsupported"})
    return entry


def _parse_toml(text):
    data = tomllib.loads(text)
    source = data.get("mcp_servers")
    if not isinstance(source, dict) or not source:
        raise ImportError_("No [mcp_servers.<name>] tables found")
    servers, warnings, skipped = {}, [], []
    for name, raw in source.items():
        if not isinstance(raw, dict) or not (raw.get("command") or raw.get("url")):
            skipped.append(name)
            continue
        servers[name] = _from_codex_entry(name, raw, warnings)
    return "toml-codex", servers, warnings, skipped


def _split_commands(text):
    joined = re.sub(r"\\\r?\n", " ", text)
    commands = []
    for line in joined.splitlines():
        line = line.strip().removeprefix("$ ").strip()
        if not line or line.startswith("#"):
            continue
        commands.append(shlex.split(line))
    return commands


def _take(argv, i, flag):
    if i + 1 >= len(argv):
        raise ImportError_(f"{flag} needs a value")
    return argv[i + 1]


def _parse_claude_add(argv, warnings):
    if argv[2] == "add-json":
        if len(argv) < 5:
            raise ImportError_("claude mcp add-json needs a name and JSON")
        name = argv[3]
        return name, _from_json_entry(name, json.loads(argv[4]), warnings)
    transport, env, headers, oauth, rest, i = "stdio", {}, {}, {}, [], 3
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            rest += argv[i + 1:]
            break
        if arg in ("-t", "--transport"):
            transport = _take(argv, i, arg).lower()
            i += 2
        elif arg in ("-s", "--scope"):
            i += 2
        elif arg in ("-e", "--env"):
            key, _, value = _take(argv, i, arg).partition("=")
            env[key] = value
            i += 2
        elif arg in ("-H", "--header"):
            key, _, value = _take(argv, i, arg).partition(":")
            headers[key.strip()] = value.strip()
            i += 2
        elif arg in ("--client-id", "--client-secret"):
            oauth["clientId" if arg == "--client-id" else "clientSecret"] = _take(argv, i, arg)
            i += 2
        elif arg.startswith("--") and "=" in arg:
            flag, value = arg.split("=", 1)
            argv[i:i + 1] = [flag, value]
        elif arg.startswith("-") and not rest:
            raise ImportError_(f"Unsupported option: {arg}")
        else:
            rest.append(arg)
            i += 1
    if len(rest) < 2:
        raise ImportError_("claude mcp add needs a name and a command or URL")
    name, target, args = rest[0], rest[1], rest[2:]
    if transport in ("http", "sse"):
        entry = {"type": transport, "url": target}
        if headers:
            entry["headers"] = headers
        if oauth:
            entry["oauth"] = oauth
    else:
        entry = {"command": target, "args": args}
        if env:
            entry["env"] = env
    entry["enabled"] = True
    return name, entry


def _parse_codex_add(argv, warnings):
    env, rest, url, bearer, client_id, i = {}, [], None, None, None, 3
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            rest += argv[i + 1:]
            break
        if arg == "--env":
            key, _, value = _take(argv, i, arg).partition("=")
            env[key] = value
            i += 2
        elif arg == "--url":
            url = _take(argv, i, arg)
            i += 2
        elif arg == "--bearer-token-env-var":
            bearer = _take(argv, i, arg)
            i += 2
        elif arg == "--oauth-client-id":
            client_id = _take(argv, i, arg)
            i += 2
        elif arg.startswith("--") and "=" in arg:
            flag, value = arg.split("=", 1)
            argv[i:i + 1] = [flag, value]
        elif arg.startswith("-") and not rest:
            raise ImportError_(f"Unsupported option: {arg}")
        else:
            rest.append(arg)
            i += 1
    if not rest:
        raise ImportError_("codex mcp add needs a name")
    name = rest[0]
    if url:
        entry = {"type": "http", "url": url}
        if bearer:
            entry["headers"] = {"Authorization": "Bearer " + _env_ref(bearer)}
        if client_id:
            entry["oauth"] = {"clientId": client_id}
    elif len(rest) >= 2:
        entry = {"command": rest[1], "args": rest[2:]}
        if env:
            entry["env"] = env
    else:
        raise ImportError_(f"{name}: codex mcp add needs a command after -- or --url")
    entry["enabled"] = True
    return name, entry


def _parse_commands(text):
    commands = _split_commands(text)
    servers, warnings, labels = {}, [], set()
    for argv in commands:
        if len(argv) >= 3 and argv[0] == "claude" and argv[1] == "mcp" and argv[2] in ("add", "add-json"):
            name, entry = _parse_claude_add(argv, warnings)
            labels.add("cli-claude")
        elif len(argv) >= 3 and argv[0] == "codex" and argv[1] == "mcp" and argv[2] == "add":
            name, entry = _parse_codex_add(argv, warnings)
            labels.add("cli-codex")
        else:
            raise ImportError_(f"Unrecognized command: {' '.join(argv[:3])}")
        servers[name] = entry
    return (labels.pop() if len(labels) == 1 else "cli-mixed"), servers, warnings, []


def points_to_hub(entry, port):
    haystack = " ".join([entry.get("url") or "", *entry.get("args", [])])
    return re.search(rf"(127\.0\.0\.1|localhost):{port}(?!\d)", haystack) is not None


def parse(text, hub_port=None):
    text = text.strip()
    if not text:
        raise ImportError_("Nothing to import")
    if text[0] in "{[" and not text.startswith("[mcp_servers"):
        try:
            label, servers, warnings, skipped = _parse_json(text)
        except json.JSONDecodeError as e:
            raise ImportError_(f"Invalid JSON: {e}")
    elif re.search(r"^\s*\[mcp_servers[.\]]", text, re.M):
        try:
            label, servers, warnings, skipped = _parse_toml(text)
        except tomllib.TOMLDecodeError as e:
            raise ImportError_(f"Invalid TOML: {e}")
    elif re.match(r"^(\$\s*)?(claude|codex)\s+mcp\s+add", text):
        try:
            label, servers, warnings, skipped = _parse_commands(text)
        except ValueError as e:
            raise ImportError_(str(e))
    else:
        raise ImportError_("Unrecognized format: expected JSON, Codex TOML or `claude mcp add` / `codex mcp add` commands")
    if hub_port:
        for name in [n for n, e in servers.items() if points_to_hub(e, hub_port)]:
            del servers[name]
            warnings.append({"server": name, "key": "", "reason": "self"})
    if not servers:
        raise ImportError_("No servers found")
    return {"format": label, "servers": servers, "warnings": warnings, "skipped": skipped}
