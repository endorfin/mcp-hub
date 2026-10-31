import re

import secrets_store

PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)")),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{50,}")),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("stripe-key", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{20,}")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("url-password", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:([^\s@/]{3,})@")),
]
SECRET_NAME = re.compile(r"token|secret|key|passw|pwd|auth|credential|cookie|session", re.I)
SCHEMES = ("Bearer ", "Basic ", "Token ")
MIN_LENGTH = 8


def entry_secrets(entry, session_headers=None):
    try:
        resolved = secrets_store.resolve_entry(entry)
    except secrets_store.SecretError:
        resolved = entry
    values = set()
    for key in ("env", "headers"):
        for name, value in (resolved.get(key) or {}).items():
            original = (entry.get(key) or {}).get(name, "")
            if key == "headers" or "${" in str(original) or SECRET_NAME.search(name):
                values.add(value)
    values |= {value for value, original in zip(resolved.get("args") or [], entry.get("args") or []) if "${" in original}
    values |= set((session_headers or {}).values())
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
    spans = _spans(text, known)
    for start, end, kind in reversed(spans):
        text = f"{text[:start]}[redacted:{kind}]{text[end:]}"
    return text, sorted({kind for _, _, kind in spans})


def redact_value(value, known=()):
    found = set()

    def walk(item):
        if isinstance(item, str):
            text, kinds = redact(item, known)
            found.update(kinds)
            return text
        if isinstance(item, dict):
            return {k: walk(v) for k, v in item.items()}
        if isinstance(item, list):
            return [walk(v) for v in item]
        return item

    return walk(value), sorted(found)
