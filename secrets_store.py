import re
import subprocess
import threading

PATTERN = re.compile(r"\$\{(op://[^}]+|keychain:[^}]+)\}")
SERVICE_PREFIX = "mcp-hub/"
ACCOUNT = "mcp-hub"

_cache = {}
_missing = set()
_lock = threading.Lock()


class SecretError(Exception):
    pass


def _run(args, stdin=None):
    try:
        done = subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise SecretError(f"{args[0]} not found")
    except subprocess.TimeoutExpired:
        raise SecretError(f"{args[0]} is not responding")
    if done.returncode:
        message = (done.stderr or done.stdout).strip()
        last = message.splitlines()[-1] if message else f"{args[0]} failed"
        raise SecretError(re.sub(r"^\[ERROR\] \S+ \S+ ", "", last))
    return done.stdout


def _lookup(ref):
    if ref.startswith("op://"):
        return _run(["op", "read", "--no-newline", ref])
    name = ref.removeprefix("keychain:")
    try:
        return _run(["security", "find-generic-password", "-a", ACCOUNT, "-s", SERVICE_PREFIX + name, "-w"]).rstrip("\n")
    except SecretError:
        raise SecretError(f"No keychain entry “{name}”")


def resolve_value(text):
    if not isinstance(text, str) or "${" not in text:
        return text

    def replace(match):
        ref = match.group(1)
        with _lock:
            if ref not in _cache:
                _cache[ref] = _lookup(ref)
            return _cache[ref]

    return PATTERN.sub(replace, text)


def resolve_entry(entry):
    resolved = dict(entry)
    for key in ("env", "headers"):
        if entry.get(key):
            resolved[key] = {k: resolve_value(v) for k, v in entry[key].items()}
    if entry.get("args"):
        resolved["args"] = [resolve_value(a) for a in entry["args"]]
    if entry.get("url"):
        resolved["url"] = resolve_value(entry["url"])
    return resolved


def store_keychain(name, value):
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", name):
        raise SecretError("Name may only contain letters, digits, . _ / -")
    if not value.isascii() or not value.isprintable():
        raise SecretError("Printable ASCII only – security returns other values as hex")
    # Pass the value via stdin, not as an argument, or it shows up in the process list.
    quoted = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    _run(["security", "-i"], f"add-generic-password -U -a {ACCOUNT} -s {SERVICE_PREFIX}{name} -w {quoted}\n")
    with _lock:
        _cache.pop(f"keychain:{name}", None)
        _missing.discard(name)
    if _lookup(f"keychain:{name}") != value:
        raise SecretError("Value in the keychain does not match")
    return "${keychain:" + name + "}"


def read_keychain(name):
    key = f"keychain:{name}"
    with _lock:
        if key in _cache:
            return _cache[key]
        if name in _missing:
            return None
    try:
        value = _lookup(key)
    except SecretError:
        value = None
    with _lock:
        if value is None:
            _missing.add(name)
        else:
            _cache[key] = value
    return value


def delete_keychain(name):
    subprocess.run(["security", "delete-generic-password", "-a", ACCOUNT, "-s", SERVICE_PREFIX + name],
                   capture_output=True)
    with _lock:
        _cache.pop(f"keychain:{name}", None)
        _missing.add(name)
