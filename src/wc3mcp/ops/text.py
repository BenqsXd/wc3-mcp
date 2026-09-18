"""The string table (war3map.wts): every piece of text a player reads that is not hardcoded in the script. Reading
it is how a map gets proofread or translated; writing it is how a name changes everywhere at once, because object
data, map info and GUI triggers all point at these entries instead of holding the words themselves.
"""
import re

from ..errors import ToolError
from .elements import _bad, _bool, _int
from .strings import load_strings, strings_file

TRIGSTR_REF = re.compile(r"TRIGSTR_(\d+)")
ALLOWED = {"set": {"op", "id", "text"}, "add": {"op", "text", "id"}, "remove": {"op", "id"},
           "replace": {"op", "find", "with", "regex", "ids"}, "import": {"op", "entries"}}
_HINT = ('ops: {"op": "set", "id": 3, "text": "Guard Tower"}, {"op": "add", "text": "New quest"}, '
         '{"op": "remove", "id": 7}, {"op": "replace", "find": "Guard", "with": "Sentry"}, '
         '{"op": "import", "entries": {"3": "Wachturm", "4": "Wache"}}')
MAX_REPORT = 500


def _used_by(project) -> dict[int, list[str]]:
    """Which files point at each string id, so a caller knows what a change touches."""
    out: dict[int, set[str]] = {}
    for f in project.list_files():
        name = f["name"]
        if name.lower().endswith((".wts", ".blp", ".dds", ".mdx", ".tga", ".mp3", ".wav", ".flac", ".ogg")):
            continue
        try:
            data = project.read(name)
        except ToolError:
            continue
        for sid in TRIGSTR_REF.findall(data.decode("utf-8", "replace")):
            out.setdefault(int(sid), set()).add(name)
    return {sid: sorted(files) for sid, files in out.items()}


def strings_get(project, query: str | None = None, limit: int = 200, offset: int = 0, used_by: bool = False) -> dict:
    """The map's text, one entry per string: its id, its text, and with used_by which files refer to it."""
    strings = load_strings(project)
    where = _used_by(project) if used_by else {}
    rows = []
    for entry in strings.entries:
        text = strings.get(entry.id) or ""
        if query and query.casefold() not in text.casefold():
            continue
        row = {"id": entry.id, "text": text}
        if used_by:
            row["used_by"] = where.get(entry.id, [])
            if not row["used_by"]:
                row["unused"] = True
        rows.append(row)
    page = rows[offset:offset + min(limit, MAX_REPORT)]
    out = {"file": strings_file(project), "total": len(strings.entries), "matched": len(rows), "offset": offset,
           "strings": page}
    if used_by:
        out["unused"] = sum(1 for row in rows if row.get("unused"))
        out["note"] = ("unused means no other file in the map holds its TRIGSTR reference: the World Editor leaves "
                       "those behind when text is deleted, and they are safe to remove")
    return out


def strings_edit(project, ops: list) -> dict:
    """All-or-nothing edits to the string table. replace goes through every entry, which is how one name changes
    everywhere a map shows it."""
    if not isinstance(ops, list) or not ops:
        raise ToolError("bad_op", "ops is a list of edits", hint=_HINT)
    strings = load_strings(project)
    before = strings.serialize()
    added, removed, changed = [], [], []
    for i, op in enumerate(ops):
        path = f"ops[{i}]"
        if not isinstance(op, dict):
            raise ToolError("bad_op", f"{path}: each op is an object", hint=_HINT)
        action = op.get("op")
        if action not in ALLOWED:
            raise ToolError("bad_op", f"{path}: unknown op {action!r}", hint=_HINT)
        extra = set(op) - ALLOWED[action]
        if extra:
            raise ToolError("bad_op", f"{path}: {action} takes no {sorted(extra)}", hint=_HINT)
        if action == "set":
            sid = _int(op.get("id"), f"{path}.id", 0)
            text = op.get("text")
            if not isinstance(text, str):
                raise _bad(f"{path}.text", "expected the text the player should read")
            if strings.get(sid) is None:
                added.append(sid)
            else:
                changed.append(sid)
            strings.set(sid, text)
        elif action == "add":
            text = op.get("text")
            if not isinstance(text, str):
                raise _bad(f"{path}.text", "expected the text the player should read")
            sid = op.get("id")
            if sid is not None:
                sid = _int(sid, f"{path}.id", 0)
                if strings.get(sid) is not None:
                    raise ToolError("id_taken", f"{path}: string {sid} already exists",
                                    hint='use {"op": "set"} to change it')
            added.append(strings.add(text, sid))
        elif action == "remove":
            sid = _int(op.get("id"), f"{path}.id", 0)
            if not strings.remove(sid):
                raise ToolError("not_found", f"{path}: no string {sid}", hint="strings_get lists them")
            removed.append(sid)
        elif action == "replace":
            find, with_ = op.get("find"), op.get("with")
            if not isinstance(find, str) or not find or not isinstance(with_, str):
                raise _bad(f"{path}.find", 'expected "find" (non-empty) and "with"')
            wanted = op.get("ids")
            if wanted is not None and (not isinstance(wanted, list)
                                       or not all(isinstance(v, int) for v in wanted)):
                raise _bad(f"{path}.ids", "expected a list of string ids to limit the replacement to")
            pattern = re.compile(find) if _bool(op.get("regex", False), f"{path}.regex") else None
            for entry in list(strings.entries):
                if wanted is not None and entry.id not in wanted:
                    continue
                text = strings.get(entry.id) or ""
                new = pattern.sub(with_, text) if pattern else text.replace(find, with_)
                if new != text:
                    strings.set(entry.id, new)
                    changed.append(entry.id)
        else:   # import: a translated table in one go
            entries = op.get("entries")
            if not isinstance(entries, dict) or not entries:
                raise _bad(f"{path}.entries", 'expected {"<id>": "text", ...}, as strings_get lists them')
            for key, text in entries.items():
                try:
                    sid = int(key)
                except (TypeError, ValueError) as e:
                    raise _bad(f"{path}.entries", "the keys are string ids") from e
                if not isinstance(text, str):
                    raise _bad(f"{path}.entries.{key}", "expected text")
                (changed if strings.get(sid) is not None else added).append(sid)
                strings.set(sid, text)
    data = strings.serialize()
    name = strings_file(project)
    if data != before:
        project.write(name, data)
    return {"file": name, "changed": data != before, "total": len(strings.entries),
            "added": sorted(set(added)), "removed": sorted(set(removed)),
            "updated": sorted(set(changed) - set(added)),
            "warnings": ["the map script keeps its own copy of trigger text: map_save (or script_build) regenerates "
                         "war3map.j or war3map.lua so the new text reaches the game"] if data != before else []}
