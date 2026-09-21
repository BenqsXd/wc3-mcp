"""Gameplay constants: the World Editor's Gameplay Constants, stored as war3mapMisc.txt in the map.

The game reads its own Units\\MiscGame.txt and Units\\MiscData.txt ([Misc] sections) and lets a map override single
keys in war3mapMisc.txt - the hero level cap, the experience formula, ability level gaps, revive costs and the rest.
An editor save keeps the file as it is.
"""
import re

from ..errors import ToolError

MAP_FILE = "war3mapMisc.txt"
SOURCES = ("Units/MiscGame.txt", "Units/MiscData.txt")
KEY = re.compile(r"^\s*([A-Za-z][\w]*)\s*=(.*)$")
NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _parse(text: str) -> dict[str, str]:
    """The [Misc] keys of a constants file, comments and blank lines dropped."""
    found = {}
    for line in text.splitlines():
        line = line.split("//", 1)[0]
        m = KEY.match(line)
        if m:
            found[m.group(1)] = m.group(2).strip()
    return found


def defaults(catalog) -> dict[str, tuple[str, str]]:
    """Every constant the game itself defines: key -> (value, the file it comes from)."""
    out: dict[str, tuple[str, str]] = {}
    for name in SOURCES:
        path = catalog.storage.resolve(name)
        data = catalog.storage.read(path) if path else None
        if data is None:
            continue
        for key, value in _parse(data.decode("utf-8", "replace")).items():
            out.setdefault(key, (value, name))
    return out


def names(catalog) -> dict[str, str]:
    """Key -> the World Editor's display name (Units/MiscMetaData.slk, field -> displayName)."""
    path = catalog.storage.resolve("Units/MiscMetaData.slk")
    data = catalog.storage.read(path) if path else None
    if not data:
        return {}
    from ..gamedata.slk import parse_slk

    return {row["field"]: catalog.westring(row.get("displayName", ""))
            for row in parse_slk(data).rows.values() if row.get("field")}


def _map_values(project) -> dict[str, str]:
    try:
        data = project.read(MAP_FILE)
    except ToolError as e:
        if e.code != "no_such_file":
            raise
        return {}
    return _parse(data.decode("utf-8", "replace"))


def _numeric(value: str) -> bool:
    return bool(NUMBER.match(value.strip()))


def values(project, catalog) -> dict[str, str]:
    """Every constant as the game reads it for this map: the game's own values with the map's own ones over them."""
    return {**{key: value for key, (value, _) in defaults(catalog).items()}, **_map_values(project)}


def constants_get(project, catalog, keys: list[str] | None = None, modified_only: bool = False,
                  query: str | None = None) -> dict:
    """The constants of the map: the game's own values with the map's own ones (war3mapMisc.txt) over them."""
    base, mine, shown = defaults(catalog), _map_values(project), names(catalog)
    unknown: list[str] = []
    if keys is not None:
        unknown = [k for k in keys if k not in base and k not in mine]
        keys = [k for k in keys if k not in unknown]
        if not keys:   # nothing left to answer, so the misspelling is the whole answer
            raise ToolError("unknown_constant", f"no gameplay constant {', '.join(unknown[:5])}",
                            hint='constants_get query="..." searches keys and display names')
    wanted = keys if keys is not None else sorted(set(base) | set(mine))
    if query:
        q = query.casefold()
        wanted = [k for k in wanted if q in k.casefold() or q in shown.get(k, "").casefold()]
    out = []
    for key in wanted:
        value, source = base.get(key, (None, None))
        row = {"key": key, "value": mine.get(key, value), "modified": key in mine}
        if shown.get(key):
            row["name"] = shown[key]
        if key in mine and value is not None:
            row["default"] = value
        if source:
            row["source"] = source
        if key not in base:
            row["unknown"] = True   # the map sets something the game does not define: a typo, or a newer build
        if modified_only and not row["modified"]:
            continue
        out.append(row)
    return {"count": len(out), "file": MAP_FILE, "has_file": bool(mine), "constants": out,
            **({"unknown": unknown} if unknown else {})}


def constants_edit(project, catalog, values: dict | None = None, reset: list[str] | None = None) -> dict:
    """Set or reset gameplay constants. Unknown keys are refused; a reset key goes back to the game's own value."""
    if not values and not reset:
        raise ToolError("bad_value", "give set (key: value) or reset (a list of keys)",
                        hint='{"set": {"MaxHeroLevel": 25}}')
    base, mine = defaults(catalog), _map_values(project)
    if values is not None and not isinstance(values, dict):
        raise ToolError("bad_value", "set must be an object of constant: value", path="set")
    for key, value in (values or {}).items():
        if key not in base:
            raise ToolError("unknown_constant", f"no gameplay constant {key!r}", path=f"set.{key}",
                            hint="constants_get lists every constant the game defines; the spelling matters")
        if isinstance(value, bool) or value is None or isinstance(value, (list, dict)):
            raise ToolError("bad_value", f"set.{key}: expected a number or text", path=f"set.{key}")
        text = str(value).strip()
        if _numeric(base[key][0]) and not _numeric(text):
            raise ToolError("bad_value", f"set.{key}: the game's own value is the number {base[key][0]}, "
                                         f"so {text!r} would be read as 0", path=f"set.{key}")
        mine[key] = text
    for key in reset or []:
        mine.pop(key, None)
    text = "[Misc]\n" + "".join(f"{key}={mine[key]}\n" for key in sorted(mine))
    data = text.encode("utf-8")
    before = None
    try:
        before = project.read(MAP_FILE)
    except ToolError as e:
        if e.code != "no_such_file":
            raise
    if mine:
        changed = data != before
        if changed:
            project.write(MAP_FILE, data)
    else:
        changed = before is not None
        if changed:
            project.delete(MAP_FILE)
    return {"changed": changed, "file": MAP_FILE, "count": len(mine),
            "constants": constants_get(project, catalog, sorted(mine))["constants"] if mine else [],
            "note": "the map script is not affected; an editor save keeps war3mapMisc.txt as it is"}
