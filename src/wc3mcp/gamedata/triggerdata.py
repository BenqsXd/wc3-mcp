"""UI/TriggerData.txt: GUI trigger categories, variable types, preset values and function signatures."""
from dataclasses import dataclass

from .profile import split_list

EVENT, CONDITION, ACTION, CALL = 0, 1, 2, 3
KIND_NAMES = ("event", "condition", "action", "call")
_SECTIONS = {"TriggerEvents": EVENT, "TriggerConditions": CONDITION, "TriggerActions": ACTION, "TriggerCalls": CALL}


@dataclass(frozen=True)
class TriggerType:
    name: str
    global_ok: bool     # usable as a global variable type
    comparable: bool
    display: str
    base: str           # underlying type (unitcode -> integer); the name itself when it has none


@dataclass(frozen=True)
class Preset:
    name: str
    type: str
    code: str
    display: str


@dataclass(frozen=True)
class Function:
    kind: int
    name: str
    args: tuple[str, ...]
    returns: str | None = None      # calls only
    display: str = ""
    layout: tuple[str, ...] = ()    # editor text pieces; "~Name" pieces are parameters
    defaults: tuple[str, ...] = ()
    category: str = ""
    script_name: str | None = None


def _text(value: str) -> str:
    return value.strip().strip('"')


class TriggerData:
    def __init__(self):
        self.categories: dict[str, tuple[str, bool]] = {}   # code -> (display name, shown before function text)
        self.types: dict[str, TriggerType] = {}
        self.presets: dict[str, Preset] = {}
        self.functions: tuple[dict[str, Function], ...] = ({}, {}, {}, {})

    @classmethod
    def parse(cls, data: bytes, westring=lambda s: s) -> "TriggerData":
        rows: dict[str, dict[str, str]] = {}
        section = None
        for line in data.decode("utf-8-sig", "replace").splitlines():
            s = line.strip()
            if not s or s.startswith("//"):
                continue
            if s.startswith("[") and "]" in s:
                section = rows.setdefault(s[1:s.index("]")], {})
            elif section is not None and "=" in s:
                key, value = s.split("=", 1)
                section[key.strip()] = value.strip()
        td = cls()
        for code, value in rows.get("TriggerCategories", {}).items():
            v = split_list(value) + ["", "", ""]
            td.categories[code] = (westring(v[0]), v[2].strip() != "1")
        for name, value in rows.get("TriggerTypes", {}).items():
            v = split_list(value) + [""] * 7
            td.types[name] = TriggerType(name, v[1] == "1", v[2] == "1", westring(v[3]), v[4] or name)
        for name, value in rows.get("TriggerParams", {}).items():
            v = split_list(value) + [""] * 4
            td.presets[name] = Preset(name, v[1], v[2], westring(_text(v[3])))
        for section_name, kind in _SECTIONS.items():
            entries = rows.get(section_name, {})
            for name, value in entries.items():
                if name.startswith("_"):
                    continue
                v = [x.strip() for x in split_list(value)]
                layout, defaults = entries.get(f"_{name}_Parameters"), entries.get(f"_{name}_Defaults")
                td.functions[kind][name] = Function(
                    kind, name, tuple(a for a in v[3 if kind == CALL else 1:] if a and a != "nothing"),
                    v[2] if kind == CALL and len(v) > 2 else None,
                    _text(entries.get(f"_{name}_DisplayName", name)),
                    tuple(split_list(layout)) if layout else (),
                    tuple(split_list(defaults)) if defaults else (),
                    entries.get(f"_{name}_Category") or entries.get(f"_{name}_CATEGORY", ""),
                    entries.get(f"_{name}_ScriptName"))
        return td

    def function(self, kind: int, name: str) -> Function | None:
        return self.functions[kind].get(name) if 0 <= kind < 4 else None

    def arg_count(self, kind: int, name: str) -> int | None:
        fn = self.function(kind, name)
        return None if fn is None else len(fn.args)

    def base(self, type_name: str) -> str:
        t = self.types.get(type_name)
        return t.base if t else type_name

    def compatible(self, expected: str, actual: str) -> bool:
        """Whether a value of type `actual` fits a parameter of type `expected`. These rules accept every enabled GUI
        function call in the 556 local Blizzard and ladder maps."""
        if actual == expected or expected == "AnyGlobal" or self.base(actual) == self.base(expected):
            return True
        if expected == "boolcall":
            return actual == "boolexpr"
        if expected.startswith("VarAsString_"):
            return actual == expected[len("VarAsString_"):].lower()
        if expected == "handle":
            return self.base(actual) not in ("integer", "real", "boolean", "string", "code")
        return expected == "musicfile" and actual == "sound"
