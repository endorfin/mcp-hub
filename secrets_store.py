import os
import re
import shutil
import subprocess
import sys
import threading

PATTERN = re.compile(r"\$\{(op://[^}]+|keychain:[^}]+|env:[^}]+)\}")
SERVICE_PREFIX = "mcp-hub/"
ACCOUNT = "mcp-hub"
# security -i cuts input lines at about 4 KB, so longer values are split. Every part but the last
# is exactly MACOS_CHUNK long, which tells the reader to fetch the next one; changing it orphans stored values.
MACOS_CHUNK = 1024

_cache = {}
_missing = set()
_lock = threading.Lock()


class SecretError(Exception):
    pass


MACOS = sys.platform == "darwin"
WINDOWS = sys.platform == "win32"


def keychain_available():
    return WINDOWS or shutil.which("security" if MACOS else "secret-tool") is not None


def _require_keychain():
    if keychain_available():
        return
    if MACOS:
        raise SecretError("security not found")
    if sys.platform.startswith("linux"):
        raise SecretError("secret-tool not found – install libsecret-tools")
    raise SecretError("The keychain is only available on macOS, Linux and Windows")


def _wincred(action, *args):
    import wincred
    try:
        return getattr(wincred, action)(*args)
    except wincred.CredentialError as e:
        raise SecretError(str(e))


def _macos_service(name, part):
    return SERVICE_PREFIX + name + (f"#{part}" if part else "")


def _keychain_read(name):
    _require_keychain()
    if WINDOWS:
        value = _wincred("read", SERVICE_PREFIX + name)
        if value is None:
            raise SecretError(f"No keychain entry “{name}”")
        return value
    if MACOS:
        value, part = "", 0
        while True:
            try:
                chunk = _run(["security", "find-generic-password", "-a", ACCOUNT, "-s", _macos_service(name, part),
                              "-w"]).rstrip("\n")
            except SecretError:
                if part == 0:
                    raise
                return value
            value += chunk
            if len(chunk) < MACOS_CHUNK:
                return value
            part += 1
    return _run(["secret-tool", "lookup", "service", SERVICE_PREFIX + name, "account", ACCOUNT])


def _keychain_write(name, value):
    _require_keychain()
    if WINDOWS:
        _wincred("write", SERVICE_PREFIX + name, ACCOUNT, value)
    elif MACOS:
        # Pass the value via stdin, not as an argument, or it shows up in the process list.
        chunks = [value[i:i + MACOS_CHUNK] for i in range(0, len(value), MACOS_CHUNK)] or [""]
        _keychain_delete(name)
        commands = []
        for part, chunk in enumerate(chunks):
            quoted = '"' + chunk.replace("\\", "\\\\").replace('"', '\\"') + '"'
            commands.append(f"add-generic-password -U -a {ACCOUNT} -s {_macos_service(name, part)} -w {quoted}\n")
        try:
            _run(["security", "-i"], "".join(commands))
        except SecretError:
            raise SecretError("security could not save the value in the keychain") from None
    else:
        _run(["secret-tool", "store", "--label", f"MCP Hub: {name}", "service", SERVICE_PREFIX + name, "account", ACCOUNT],
             value)


def _keychain_delete(name):
    if not keychain_available():
        return
    if WINDOWS:
        _wincred("delete", SERVICE_PREFIX + name)
    elif MACOS:
        part = 0
        while subprocess.run(["security", "delete-generic-password", "-a", ACCOUNT, "-s", _macos_service(name, part)],
                             capture_output=True).returncode == 0:
            part += 1
    else:
        subprocess.run(["secret-tool", "clear", "service", SERVICE_PREFIX + name, "account", ACCOUNT],
                       capture_output=True)


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
    if ref.startswith("env:"):
        name = ref.removeprefix("env:")
        if name not in os.environ:
            raise SecretError(f"Environment variable {name} is not set")
        return os.environ[name]
    if ref.startswith("op://"):
        return _run(["op", "read", "--no-newline", ref])
    name = ref.removeprefix("keychain:")
    _require_keychain()
    try:
        return _keychain_read(name)
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
    for key in ("url", "cwd"):
        if entry.get(key):
            resolved[key] = resolve_value(entry[key])
    return resolved


def store_keychain(name, value):
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", name):
        raise SecretError("Name may only contain letters, digits, . _ / -")
    if MACOS and (not value.isascii() or not value.isprintable()):
        raise SecretError("Printable ASCII only – security returns other values as hex")
    _keychain_write(name, value)
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
    _keychain_delete(name)
    with _lock:
        _cache.pop(f"keychain:{name}", None)
        _missing.add(name)
