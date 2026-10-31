import re

import secrets_store

PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)")),
    ("aws-key", re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])")),
    ("github-token", re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})")),
    ("gitlab-token", re.compile(r"(?<![A-Za-z0-9_-])glpat-[A-Za-z0-9_-]{20,}")),
    ("slack-token", re.compile(r"(?<![A-Za-z0-9-])xox[abposr]-[A-Za-z0-9-]{10,}")),
    ("stripe-key", re.compile(r"(?<![A-Za-z0-9_])[sr]k_live_[A-Za-z0-9]{20,}")),
    ("anthropic-key", re.compile(r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"(?<![A-Za-z0-9_-])sk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("google-key", re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}")),
    ("jwt", re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("url-password", re.compile(r"(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*://[^\s:/@]+:([^\s@/]{3,})@")),
]
SECRET_NAME = re.compile(r"token|secret|key|passw|pwd|auth|credential|cookie|session", re.I)
SCHEMES = ("Bearer ", "Basic ", "Token ")
MIN_LENGTH = 8


def entry_secrets(entry, resolve=True):
    try:
        resolved = secrets_store.resolve_entry(entry) if resolve else entry
    except secrets_store.SecretError:
        resolved = entry
    values = set()
    for key in ("env", "headers"):
        for name, value in (resolved.get(key) or {}).items():
            original = (entry.get(key) or {}).get(name, "")
            if (key == "headers" or "${" in str(original) or SECRET_NAME.search(name)) and "${" not in str(value):
                values.add(value)
    values |= {value for value, original in zip(resolved.get("args") or [], entry.get("args") or [])
               if "${" in original and "${" not in value}
    return _usable(values)


def header_secrets(headers):
    return _usable((headers or {}).values())


def _usable(values):
    values = {v.split(" ", 1)[1] if isinstance(v, str) and v.startswith(SCHEMES) else v for v in values}
    return {v for v in values if isinstance(v, str) and len(v) >= MIN_LENGTH}


def _spans(text, known):
    spans = []
    for value in known:
        start = text.find(value)
        while start != -1:
            spans.append((start, start + len(value), "hub-secret"))
            start = text.find(value, start + len(value))
    for kind, pattern in PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span(1) if match.groups() else match.span()
            spans.append((start, end, kind))
    spans.sort(key=lambda s: (s[0], -s[1]))
    merged = []
    for span in spans:
        if merged and span[0] < merged[-1][1]:
            continue
        merged.append(span)
    return merged


def redact(text, known=()):
    parts, last = [], 0
    spans = _spans(text, known)
    for start, end, kind in spans:
        parts += [text[last:start], f"[redacted:{kind}]"]
        last = end
    return "".join(parts) + text[last:], sorted({kind for _, _, kind in spans})


def redact_value(value, known=()):
    found = set()

    def walk(item):
        if isinstance(item, str):
            text, kinds = redact(item, known)
            found.update(kinds)
            return text
        if isinstance(item, dict):
            return {walk(k): walk(v) for k, v in item.items()}
        if isinstance(item, list):
            return [walk(v) for v in item]
        return item

    return walk(value), sorted(found)
