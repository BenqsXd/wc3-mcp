"""INI-like 'profile' text files: *Func.txt, *Strings.txt, *Skin.txt, WorldEditStrings.txt."""


def parse_profile(data: bytes, into: dict | None = None) -> dict[str, dict[str, str]]:
    out = {} if into is None else into
    section = None
    for line in data.decode("utf-8-sig", "replace").splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        if s.startswith("[") and "]" in s:
            section = out.setdefault(s[1:s.index("]")], {})
        elif section is not None and "=" in s:
            key, value = s.split("=", 1)
            section[key.strip().lower()] = value.strip()
    return out


def split_list(value: str) -> list[str]:
    """Split a comma list, honoring double-quoted items (quotes removed)."""
    items, cur, quoted = [], [], False
    for ch in value:
        if ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            items.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    items.append("".join(cur))
    return items


def unquote(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value
