import re
import unicodedata

PATTERNS = [
    ("instruction-override", re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|other|system)\b[^.\n]{0,20}"
        r"\b(instructions?|prompts?|rules|guidelines|directions)\b|\byou are now\b|\bnew system prompt\b", re.I)),
    ("concealment", re.compile(
        r"\b(do not|don't|never|without)\b[^.\n]{0,30}\b(tell(ing)?|inform(ing)?|mention(ing)?|reveal(ing)?|notify(ing)?|show(ing)?)\b"
        r"[^.\n]{0,20}\b(the )?user\b|\b(hide|conceal|keep)\b[^.\n]{0,20}\bfrom the user\b", re.I)),
    ("hidden-tags", re.compile(r"<\s*/?\s*(important|system|instructions?|secret|hidden)\s*>|\[/?INST\]|<\|im_start\|>", re.I)),
    ("sensitive-path", re.compile(
        r"~/\.ssh\b|\bid_(rsa|ed25519|ecdsa|dsa)\b|\.aws/credentials|\.netrc\b|\.npmrc\b|\.pypirc\b"
        r"|\.git-credentials\b|\.kube/config\b|/etc/(passwd|shadow)\b|\.docker/config\.json|\.config/gh/hosts"
        r"|\bmcp\.json\b|claude_desktop_config\.json", re.I)),
    ("tool-shadowing", re.compile(
        r"\b(before|instead of|after)\b[^.\n]{0,20}\b(using|calling|invoking|running)\b[^.\n]{0,20}\b(any|every|all|other|the)\b[^.\n]{0,20}\btools?\b"
        r"|\b(always|must)\b[^.\n]{0,20}\b(call|use|run)\b[^.\n]{0,15}\bthis tool (first|before)\b", re.I)),
    ("encoded-payload", re.compile(r"(?<![A-Za-z0-9+/,])[A-Za-z0-9+/]{120,}={0,2}")),
]


def _is_hidden(ch):
    return unicodedata.category(ch) == "Cf" or 0xE0000 <= ord(ch) <= 0xE007F


def _visible(text):
    return "".join(f"<U+{ord(ch):04X}>" if _is_hidden(ch) else ch for ch in text)


def _strings(item):
    stack = [(key, value) for key, value in reversed(list(item.items())) if key != "icons"]
    while stack:
        path, value = stack.pop()
        if isinstance(value, str):
            yield path, value
        elif isinstance(value, dict):
            for key, child in reversed(list(value.items())):
                stack += [(f"{path}.{key}", child), (f"{path}.{key}", str(key))]
        elif isinstance(value, list):
            stack += [(f"{path}[{index}]", child) for index, child in reversed(list(enumerate(value)))]


def scan(item):
    findings = []
    for field, text in _strings(item):
        first = next((index for index, ch in enumerate(text) if _is_hidden(ch)), None)
        if first is not None:
            findings.append({"rule": "hidden-characters", "field": field,
                             "excerpt": _visible(text[max(0, first - 40):first + 40])})
        for rule, pattern in PATTERNS:
            match = pattern.search(text)
            if match:
                start, end = max(0, match.start() - 40), min(len(text), match.end() + 40)
                findings.append({"rule": rule, "field": field,
                                 "excerpt": ("…" if start else "") + _visible(text[start:end]) + ("…" if end < len(text) else "")})
    return findings
