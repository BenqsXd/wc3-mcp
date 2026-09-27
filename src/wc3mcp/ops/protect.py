"""Map protection: a playable copy the World Editor refuses to open and that carries no editor sources.

The protected copy keeps only what the game reads. It drops the editor-only files (GUI triggers, trigger text,
placed units, regions, cameras, sounds, import list) and the listfile, cuts war3map.w3i after the forces (the game
never reads the rest; the editor refuses the file) and obfuscates the map script. Nothing removed is kept in the
protected file, so it cannot be turned back into an editable map from the file alone. Unprotecting is a restore:
the original is kept in this server's vault under the protected file's hash, so only the machine that protected a
map can unprotect it, and only maps protected here.
"""
import hashlib
import json
import re
import secrets
import shutil
import time
from pathlib import Path

from .. import config
from ..errors import ToolError
from ..formats import w3i
from ..formats.binary import FormatError
from ..gamedata import natives as natives_module
from ..mpq.reader import Archive, MpqError
from ..mpq.writer import SPECIAL, write_archive
from ..project.workspace import write_file
from ..script import luacheck

EDITOR_ONLY = {"war3map.wtg", "war3map.wct", "war3mapunits.doo", "war3map.w3r", "war3map.w3c", "war3map.w3s",
               "war3map.imp"}
SCRIPTS = {"war3map.j": "jass", "scripts\\war3map.j": "jass", "war3map.lua": "lua", "scripts\\war3map.lua": "lua"}
ENTRY_POINTS = {"main", "config"}   # the game calls these by name
LUA_STD = set("""_G _ENV assert collectgarbage coroutine debug dofile error getmetatable io ipairs load loadfile math
next os package pairs pcall print rawequal rawget rawlen rawset require select setmetatable string table tonumber
tostring type unpack utf8 xpcall FourCC""".split())

JASS_TOKEN = re.compile(r"""(?P<ws>[ \t]+)|(?P<nl>\r\n|\n|\r)|(?P<com>//[^\r\n]*)|(?P<str>"(?:\\.|[^"\\])*")
    |(?P<raw>'[^']*')|(?P<id>[A-Za-z_]\w*)|(?P<num>\$[0-9A-Fa-f]+|0[xX][0-9A-Fa-f]+|\d+\.?\d*|\.\d+)|(?P<op>.)""",
                        re.S | re.X)
JASS_KEYWORDS = set("""function takes returns endfunction native constant globals endglobals local set call if then
else elseif endif loop endloop exitwhen return array and or not true false null nothing type extends
debug""".split())
IDENT = re.compile(r"[A-Za-z_]\w*")


def vault() -> Path:
    return config.home() / "protected"


def _game_names(catalog) -> set[str]:
    """The types, natives, functions and globals of common.j, Blizzard.j and common.ai: never renamed (in Lua the
    game's Blizzard.lua has the same names)."""
    names = set()
    for rel in natives_module.SOURCES:
        data = catalog._read(rel)
        if data is not None:
            top, _, natives, types = _declarations(_jass_lines(data.decode("utf-8", "replace"))[0])
            names |= top | natives | types
    return names


def _jass_lines(text: str):
    """Token lines without comments, and all tokens."""
    toks = [(m.lastgroup, m.group()) for m in JASS_TOKEN.finditer(text)]
    lines, line = [], []
    for kind, value in toks:
        if kind == "nl":
            lines.append(line)
            line = []
        elif kind != "com":
            line.append((kind, value))
    lines.append(line)
    return lines, toks


def _declarations(lines):
    """(functions and globals, locals and parameters, natives, types) declared in JASS token lines."""
    top, inner, natives, types, in_globals = set(), set(), set(), set(), False
    for line in lines:
        ids = [v for k, v in line if k == "id"]
        if not ids:
            continue
        if ids[0] == "globals":
            in_globals = True
        elif ids[0] == "endglobals":
            in_globals = False
        elif in_globals:
            words = ids[1:] if ids[0] == "constant" else ids
            if len(words) >= 2:
                top.add(words[2] if words[1] == "array" and len(words) > 2 else words[1])
        elif ids[0] == "type" and len(ids) >= 2:
            types.add(ids[1])
        elif ids[0] in ("function", "native") or ids[:2] in (["constant", "native"], ["constant", "function"]):
            words = ids[1:] if ids[0] == "constant" else ids
            if len(words) < 2:
                continue
            (natives if words[0] == "native" else top).add(words[1])
            if words[0] == "function" and "takes" in words and "returns" in words:
                params = words[words.index("takes") + 1:words.index("returns")]
                inner.update(params[1::2] if params != ["nothing"] else [])
        elif ids[0] == "local" and len(ids) >= 3:
            inner.add(ids[3] if ids[2] == "array" and len(ids) > 3 else ids[2])
    return top, inner, natives, types


def _string_names(literals) -> set[str]:
    """Names a script could look up by string (ExecuteFunc, _G[...]): any literal that is a whole identifier."""
    return {s[1:-1] for s in literals if IDENT.fullmatch(s[1:-1])}


class _Names:
    """Random identifiers from a look-alike alphabet, fresh for every protection (nothing to map back)."""
    def __init__(self, taken: set[str]):
        self.taken, self.map = set(taken), {}

    def __call__(self, name: str) -> str:
        if name not in self.map:
            while True:
                new = secrets.choice("lI") + "".join(secrets.choice("lI1") for _ in range(11))
                if new not in self.taken:
                    break
            self.taken.add(new)
            self.map[name] = new
        return self.map[name]


def obfuscate_jass(text: str, game_names: set[str]) -> tuple[str, int]:
    """Rename every function, global, local and parameter the script declares; drop comments, indentation and blank
    lines. JASS statements end at line ends, so line breaks between statements stay."""
    lines, toks = _jass_lines(text)
    top, inner, natives, _ = _declarations(lines)
    declared = top | inner
    computed, calls = _execute_func_args(lines)
    # ExecuteFunc("Name") literals are renamed with their function; any other string naming it keeps the name
    literals = [v for li, line in enumerate(lines) for ti, (k, v) in enumerate(line) if k == "str" and (li, ti) not in calls]
    keep = JASS_KEYWORDS | ENTRY_POINTS | natives | game_names | _string_names(literals)
    if computed:   # a function name built at run time: functions keep their names
        keep |= _function_names(lines)
    rename = _Names({v for k, v in toks if k == "id"} | keep)
    out = []
    for li, line in enumerate(lines):
        parts = []
        for ti, (k, v) in enumerate(line):
            if k == "ws":
                if parts and parts[-1] != " ":
                    parts.append(" ")
            elif k == "id" and v in declared and v not in keep:
                parts.append(rename(v))
            elif (li, ti) in calls and v[1:-1] in declared and v[1:-1] not in keep:
                parts.append(f'"{rename(v[1:-1])}"')
            else:
                parts.append(v)
        s = "".join(parts).strip(" ")
        if s:
            out.append(s)
    return "\r\n".join(out) + "\r\n", len(rename.map)


def _execute_func_args(lines) -> tuple[bool, set[tuple[int, int]]]:
    """(some ExecuteFunc call builds its name at run time, positions of the string literals ExecuteFunc gets)."""
    computed, literal = False, set()
    for li, line in enumerate(lines):
        solid = [(ti, k, v) for ti, (k, v) in enumerate(line) if k != "ws"]
        for i, (_, k, v) in enumerate(solid[:-2]):
            if k == "id" and v == "ExecuteFunc" and solid[i + 1][2] == "(":
                ti, kind, _ = solid[i + 2]
                end = solid[i + 3][2] if i + 3 < len(solid) else None
                if kind == "str" and end == ")":
                    literal.add((li, ti))
                else:
                    computed = True
    return computed, literal


def _function_names(lines) -> set[str]:
    names = set()
    for line in lines:
        ids = [v for k, v in line if k == "id"]
        if len(ids) >= 2 and ids[0] == "function":
            names.add(ids[1])
    return names


def obfuscate_lua(text: str, game_names: set[str]) -> tuple[str, int]:
    """Rename the map's own global functions and its udg_/gg_/Trig_ globals, drop comments and layout. A name is
    renamed only when it never appears as a field (after . or :), a table key or a whole string literal."""
    toks = luacheck.tokenize(text)
    if any(t == "<error>" for t, _, _ in toks):
        raise ToolError("bad_script", "war3map.lua does not parse", hint="script_validate names the error")
    values = [text[s:e] for _, s, e in toks]
    candidates, blocked, depth = set(), set(), 0
    for i, (t, _, _) in enumerate(toks):
        if t in ("{", "}"):
            depth += 1 if t == "{" else -1
        if t != "<name>":
            continue
        name, prev = values[i], toks[i - 1][0] if i else None
        nxt = toks[i + 1][0] if i + 1 < len(toks) else None
        if prev in (".", ":") or (depth > 0 and prev in ("{", ",", ";") and nxt == "="):
            blocked.add(name)
        elif prev == "function" and nxt == "(" or name.startswith(("udg_", "gg_", "Trig_", "InitTrig_")):
            candidates.add(name)
    literals = [values[i] for i, (t, _, _) in enumerate(toks) if t == "<string>"]
    strings = {s.strip("\"'") for s in literals}
    keep = blocked | ENTRY_POINTS | LUA_STD | game_names | {s for s in strings if IDENT.fullmatch(s)}
    rename = _Names({v for (t, _, _), v in zip(toks, values) if t == "<name>"} | keep)
    out = [rename(v) if t == "<name>" and v in candidates and v not in keep else v
           for (t, _, _), v in zip(toks, values) if t != "<eof>"]
    return " ".join(out) + "\n", len(rename.map)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def protect(source, catalog, dest=None) -> dict:
    source = Path(source).resolve()
    if not source.is_file():
        raise ToolError("not_found", f"map file not found: {source}",
                        hint="protect a .w3x/.w3m file (map_save format=mpq writes one from a map folder)")
    dest = Path(dest).resolve() if dest else source.with_name(f"{source.stem}_protected{source.suffix}")
    if dest == source:
        raise ToolError("bad_value", "dest must differ from the map: the original stays as it is", path="dest")
    original = source.read_bytes()
    try:
        arc = Archive(original, str(source))
        files = {n: arc.read(n) for n in arc.list() if n not in SPECIAL}
    except MpqError as e:
        raise ToolError("bad_archive", f"cannot read map: {e}") from e
    lower = {n.lower(): n for n in files}
    if arc.unnamed_entries(arc.list()):
        raise ToolError("already_protected", f"{source.name} holds files without names (a protected map?)",
                        hint="protect the editable original")
    scripts = [lower[n] for n in SCRIPTS if n in lower]
    if not scripts or "war3map.w3i" not in lower:
        raise ToolError("no_script", f"{source.name} has no map script or no war3map.w3i",
                        hint="save the map once (map_save or the World Editor) so it has a script to play from")
    try:
        info = w3i.parse(files[lower["war3map.w3i"]])
    except FormatError as e:
        raise ToolError("bad_file", f"war3map.w3i: {e}") from e
    if info.truncated:
        raise ToolError("already_protected", f"{source.name} is already protected", hint="protect the original")

    game_names = _game_names(catalog)
    renamed = 0
    for name in scripts:
        text = files[name].decode("utf-8", "surrogateescape")
        if SCRIPTS[name.lower()] == "jass":
            obf, n = obfuscate_jass(text, game_names)
        else:
            obf, n = obfuscate_lua(text, game_names)
        files[name] = obf.encode("utf-8", "surrogateescape")
        renamed += n
    info.truncated, info.trailing = True, b""
    files[lower["war3map.w3i"]] = w3i.serialize(info)
    removed = sorted(n for n in files if n.lower() in EDITOR_ONLY)
    kept = {n: d for n, d in files.items() if n.lower() not in EDITOR_ONLY}
    data = write_archive(kept, prefix=arc.prefix, listfile=False)

    digest = _sha(data)
    vault().mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, vault() / f"{digest}{source.suffix}")
    (vault() / f"{digest}.json").write_text(json.dumps(
        {"original_name": source.name, "original_path": str(source), "original_sha256": _sha(original),
         "protected_path": str(dest), "protected_at": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1), "utf-8")
    backup = write_file(dest, data)
    return {"protected": str(dest), "original": str(source), "size": len(data), "removed": removed,
            "script": {"files": scripts, "renamed": renamed}, "sha256": digest, "backup": backup,
            "vault": str(vault() / f"{digest}{source.suffix}")}


def unprotect(path, dest=None) -> dict:
    """Restore the original of a map protected on this machine. Maps protected elsewhere have no vault entry."""
    path = Path(path).resolve()
    if not path.is_file():
        raise ToolError("not_found", f"map file not found: {path}")
    digest = _sha(path.read_bytes())
    meta_file = vault() / f"{digest}.json"
    if not meta_file.is_file():
        raise ToolError("not_ours", f"{path.name} was not protected by this server (or was changed since)",
                        hint="only maps protected with map_protect on this machine can be restored")
    meta = json.loads(meta_file.read_text("utf-8"))
    original = (vault() / f"{digest}{Path(meta['original_name']).suffix}").read_bytes()
    if _sha(original) != meta["original_sha256"]:
        raise ToolError("vault_damaged", f"the stored original of {path.name} does not match its record")
    dest = Path(dest).resolve() if dest else path.with_name(meta["original_name"])
    if dest == path:
        raise ToolError("bad_value", "dest must differ from the protected map", path="dest")
    if dest.is_file() and _sha(dest.read_bytes()) == meta["original_sha256"]:
        return {"restored": str(dest), "unchanged": True, "sha256": meta["original_sha256"]}
    backup = write_file(dest, original)
    return {"restored": str(dest), "sha256": meta["original_sha256"], "backup": backup,
            "protected_at": meta["protected_at"]}
