"""GUI triggers: ECA trees as JSON, editor-style text, and checks against TriggerData."""
import re

from ..errors import ToolError
from ..formats.wtg import ECA, FUNCTION, INVALID, PRESET, STRING, VARIABLE, Call, Param
from ..formats.wts import TRIGSTR
from ..gamedata.triggerdata import ACTION, CALL, CONDITION, EVENT, KIND_NAMES

GENERATED = {"gg_trg_": "trigger", "gg_rct_": "rect", "gg_snd_": "sound", "gg_cam_": "camerasetup",
             "gg_unit_": "unit", "gg_item_": "item", "gg_dest_": "destructable"}
CODE_KINDS = {"code": ACTION, "boolexpr": CONDITION, "boolcall": CONDITION, "eventcall": EVENT}
CODE_RETURNS = {EVENT: "eventcall", CONDITION: "boolexpr", ACTION: "code"}
RAWCODE_TYPES = {"unitcode": "unit", "itemcode": "item", "abilcode": "ability", "buffcode": "buff",
                 "techcode": "upgrade", "destructablecode": "destructible", "doodadcode": "doodad",
                 "heroskillcode": "ability"}
_BLOCKS = {"IfThenElseMultiple": (("if", CONDITION, "If - Conditions"), ("then", ACTION, "Then - Actions"),
                                  ("else", ACTION, "Else - Actions")),
           "AndMultiple": (("conditions", CONDITION, "Conditions"),),
           "OrMultiple": (("conditions", CONDITION, "Conditions"),)}
_LOOP = (("actions", ACTION, "Loop - Actions"),)
_ARG_HINT = 'an argument is a literal, {"preset": name}, {"var": name, "index": arg} or {"call": name, "args": [...]}'


def blocks(name: str) -> tuple[tuple[str, int, str], ...]:
    """Child blocks of a block function by group index: (JSON key, kind of its functions, editor label)."""
    return _BLOCKS.get(name) or (_LOOP if name.endswith("Multiple") else ())


def script_name(name: str) -> str:
    """The identifier the editor derives from a trigger name (gg_trg_<this>): trailing spaces dropped, leading kept,
    and a trailing '_' followed by 'u' (JASS identifiers cannot end with an underscore). Every byte of a non-ASCII
    character becomes its own '_', as in the editor."""
    ident = re.sub(rb"[^A-Za-z0-9_]", b"_", name.rstrip().encode("utf-8", "surrogateescape")).decode("ascii")
    return ident + "u" if ident.endswith("_") else ident


def var_type(name: str, variables: dict) -> str | None:
    v = variables.get(name)
    if v is not None:
        return v.type
    return next((t for prefix, t in GENERATED.items() if name.startswith(prefix)), None)


def _argument_types(fn, first_var: str | None, variables: dict) -> list[str]:
    args = list(fn.args)
    if fn.name == "SetVariable" and len(args) == 2:
        args[1] = (var_type(first_var, variables) if first_var else None) or "?"
    return args


def literal_text(value) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, "f").rstrip("0").rstrip(".") or "0"
    return value if isinstance(value, str) else None


# ---- JSON ------------------------------------------------------------------------------------------------------
def param_json(p: Param):
    if p.type == STRING:
        return p.value
    if p.type == PRESET:
        return {"preset": p.value}
    if p.type == VARIABLE:
        return {"var": p.value, "index": param_json(p.index)} if p.index is not None else {"var": p.value}
    if p.type == FUNCTION and p.call is not None:
        out = {"call": p.call.name}
        if p.call.params:
            out["args"] = [param_json(x) for x in p.call.params]
        return out
    return None


def eca_json(e: ECA) -> dict:
    out = {"fn": e.name}
    if e.params:
        out["args"] = [param_json(p) for p in e.params]
    if not e.enabled:
        out["enabled"] = False
    specs = blocks(e.name)
    for c in e.children:
        item = eca_json(c)
        if 0 <= c.group < len(specs):
            out.setdefault(specs[c.group][0], []).append(item)
        else:  # leftovers the editor keeps after a block function was replaced
            out.setdefault("children", []).append({**item, "group": c.group})
    return out


def _bad(path: str, message: str, **details) -> ToolError:
    return ToolError("bad_value", f"{path}: {message}", path=path, **details)


def _function(td, kind: int, name, path: str):
    fn = td.function(kind, name) if isinstance(name, str) else None
    if fn is None:
        other = [KIND_NAMES[k] for k in range(4) if k != kind and isinstance(name, str) and td.function(k, name)]
        raise ToolError("unknown_function", f"{path}: no {KIND_NAMES[kind]} named {name!r}"
                        + (f" ({name} is a {' / '.join(other)})" if other else ""),
                        hint="data_search kind=trigger_function finds functions", path=path)
    return fn


def _params(fn, args, td, variables: dict, path: str) -> list[Param]:
    args = [] if args is None else args
    if not isinstance(args, list):
        raise _bad(path, "args must be a list")
    first = args[0].get("var") if args and isinstance(args[0], dict) else None
    types = _argument_types(fn, first if isinstance(first, str) else None, variables)
    if len(args) != len(types):
        raise _bad(path, f"{fn.name} takes {len(types)} arguments ({', '.join(types) or 'none'}), got {len(args)}")
    return [param_from_json(a, t, td, variables, f"{path}.args[{i}]") for i, (a, t) in enumerate(zip(args, types))]


def param_from_json(value, expected: str, td, variables: dict, path: str) -> Param:
    if value is None:
        return Param(INVALID, "")
    text = literal_text(value)
    if text is not None:
        return Param(STRING, text)
    if isinstance(value, dict):
        keys = set(value)
        if keys == {"preset"} and isinstance(value["preset"], str):
            return Param(PRESET, value["preset"])
        if "var" in keys and keys <= {"var", "index"} and isinstance(value["var"], str):
            index = param_from_json(value["index"], "integer", td, variables, path + ".index") if "index" in keys else None
            return Param(VARIABLE, value["var"], index=index)
        if "call" in keys and keys <= {"call", "args"}:
            kind = CODE_KINDS.get(expected, CALL)
            fn = _function(td, kind, value["call"], path)
            params = _params(fn, value.get("args"), td, variables, path)
            return Param(FUNCTION, fn.name if kind in (CALL, ACTION) else "", Call(kind, fn.name, params))
    raise _bad(path, "unrecognized argument", hint=_ARG_HINT)


def ecas_from_json(items, kind: int, td, variables: dict, path: str) -> list[ECA]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise _bad(path, "must be a list of functions")
    out = []
    for i, item in enumerate(items):
        where = f"{path}[{i}]"
        if not isinstance(item, dict) or "fn" not in item:
            raise _bad(where, 'expected {"fn": name, "args": [...]}')
        fn = _function(td, kind, item["fn"], where)
        specs = blocks(fn.name)
        extra = set(item) - {"fn", "args", "enabled"} - {key for key, _, _ in specs}
        if extra:
            raise _bad(where, f"unknown keys {sorted(extra)}")
        e = ECA(kind, fn.name, 0 if item.get("enabled") is False else 1, _params(fn, item.get("args"), td, variables, where))
        for group, (key, child_kind, _) in enumerate(specs):
            for child in ecas_from_json(item.get(key), child_kind, td, variables, f"{where}.{key}"):
                child.group = group
                e.children.append(child)
        out.append(e)
    return out


# ---- checks ----------------------------------------------------------------------------------------------------
class Checker:
    """Finds what would break script generation in enabled GUI code; silent on all enabled code in 556 local maps."""

    def __init__(self, td, variables: dict, trigger_names: set[str]):
        self.td, self.variables, self.trigger_names = td, variables, trigger_names
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def ecas(self, ecas: list[ECA], path: str) -> None:
        for i, e in enumerate(ecas):
            self._eca(e, e.kind, f"{path}[{i}]")

    def _eca(self, e: ECA, kind: int, path: str) -> None:
        if not e.enabled:
            return
        if e.kind != kind:
            self.errors.append(f"{path}: {e.name} is a {KIND_NAMES[e.kind]}, but this block takes {KIND_NAMES[kind]}s")
        fn = self.td.function(e.kind, e.name)
        if fn is None:
            self.errors.append(f"{path}: unknown {KIND_NAMES[e.kind]} {e.name!r}")
            return
        self._params(fn, e.params, f"{path}.{e.name}")
        specs = blocks(e.name)
        for i, c in enumerate(e.children):
            if 0 <= c.group < len(specs):
                self._eca(c, specs[c.group][1], f"{path}.{specs[c.group][0]}[{i}]")
            else:
                self._eca(c, c.kind, f"{path}.children[{i}]")

    def _params(self, fn, params: list[Param], path: str) -> None:
        first = params[0].value if params and params[0].type == VARIABLE else None
        if fn.name == "SetVariable" and first is None:
            self.errors.append(f"{path}: the first argument must be a variable")
            return
        types = _argument_types(fn, first, self.variables)
        if len(params) != len(types):
            self.errors.append(f"{path}: takes {len(types)} arguments, got {len(params)}")
            return
        for i, (p, t) in enumerate(zip(params, types)):
            self._param(p, t, f"{path}.args[{i}]")

    def _param(self, p: Param, expected: str, path: str) -> None:
        if p.type == STRING:
            self.literal(p.value, expected, path)
            return
        if p.type == PRESET:
            preset = self.td.presets.get(p.value)
            if preset is None:
                self.errors.append(f"{path}: unknown preset {p.value!r}")
                return
            actual = preset.type
        elif p.type == VARIABLE:
            actual = var_type(p.value, self.variables)
            if actual is None:
                self.errors.append(f"{path}: unknown variable {p.value!r}")
                return
            if p.value.startswith("gg_trg_") and p.value[len("gg_trg_"):] not in self.trigger_names:
                self.warnings.append(f"{path}: no trigger matches {p.value!r}")
            v = self.variables.get(p.value)
            if v is not None and bool(v.is_array) != (p.index is not None):
                self.errors.append(f"{path}: {p.value} is {'an array and needs' if v.is_array else 'not an array and takes no'} index")
            if p.index is not None:
                self._param(p.index, "integer", path + ".index")
        elif p.type == FUNCTION and p.call is not None:
            fn = self.td.function(p.call.kind, p.call.name)
            if fn is None:
                self.errors.append(f"{path}: unknown {KIND_NAMES[p.call.kind]} {p.call.name!r}")
                return
            self._params(fn, p.call.params or [], f"{path}.{fn.name}")
            actual = fn.returns if p.call.kind == CALL else CODE_RETURNS[p.call.kind]
        else:
            self.errors.append(f"{path}: argument is not set")
            return
        if not self.td.compatible(expected, actual or "nothing"):
            self.errors.append(f"{path}: expects {expected}, got {actual}")

    def literal(self, value: str, expected: str, path: str) -> None:
        if expected in RAWCODE_TYPES:
            ok = len(value.encode("utf-8")) == 4
        elif expected == "integer":
            ok = re.fullmatch(r"-?\d+", value) is not None
        elif expected == "real":
            try:
                float(value)
                ok = True
            except ValueError:
                ok = False
        elif expected == "boolean":
            ok = value in ("true", "false")
        else:
            return
        if not ok:
            self.errors.append(f"{path}: {value!r} is not a valid {expected}")


# ---- editor text -----------------------------------------------------------------------------------------------
class Renderer:
    """Editor-style text for GUI functions."""

    def __init__(self, td, catalog, variables: dict, strings):
        self.td, self.catalog, self.variables, self.strings = td, catalog, variables, strings

    def lines(self, ecas: list[ECA]) -> list[str]:
        out = []
        for title, kind in (("Events", EVENT), ("Conditions", CONDITION), ("Actions", ACTION)):
            out.append(title)
            for e in ecas:
                if e.kind == kind:
                    self._eca(e, 1, out)
        return out

    def _eca(self, e: ECA, depth: int, out: list[str]) -> None:
        fn = self.td.function(e.kind, e.name)
        text = self.call(fn, e.name, e.params)
        category = self.td.categories.get(fn.category) if fn else None
        if category and category[1] and category[0]:
            text = f"{category[0]} - {text}"
        out.append("    " * depth + ("" if e.enabled else "(disabled) ") + text)
        for group, (_, _, label) in enumerate(blocks(e.name)):
            out.append("    " * (depth + 1) + label)
            for c in e.children:
                if c.group == group:
                    self._eca(c, depth + 2, out)

    def call(self, fn, name: str, params: list[Param]) -> str:
        if fn is None:
            return f"{name}({', '.join(self.param(p, '') for p in params)})"
        first = params[0].value if params and params[0].type == VARIABLE else None
        types = _argument_types(fn, first, self.variables)
        pieces = list(fn.layout)
        if len(pieces) > 1 and pieces[0] == fn.display:
            pieces = pieces[1:]
        slots = [i for i, piece in enumerate(pieces) if piece.startswith("~")]
        if not pieces or len(slots) != len(params):
            if not params:
                return fn.display
            return f"{fn.display}({', '.join(self.param(p, t) for p, t in zip(params, types))})"
        for slot, p, t in zip(slots, params, types):
            pieces[slot] = self.param(p, t)
        return "".join(pieces)

    def param(self, p: Param, expected: str) -> str:
        if p.type == STRING:
            if TRIGSTR.match(p.value):
                return self.strings.resolve(p.value)
            kind = RAWCODE_TYPES.get(expected)
            name = self.catalog.name(kind, p.value) if kind and len(p.value) == 4 else ""
            return name or p.value
        if p.type == PRESET:
            preset = self.td.presets.get(p.value)
            return preset.display if preset and preset.display else p.value
        if p.type == VARIABLE:
            prefix = next((x for x in GENERATED if p.value.startswith(x)), None)
            text = p.value[len(prefix):].replace("_", " ") + " <gen>" if prefix else p.value
            return f"{text}[{self.param(p.index, 'integer')}]" if p.index is not None else text
        if p.type == FUNCTION and p.call is not None:
            return f"({self.call(self.td.function(p.call.kind, p.call.name), p.call.name, p.call.params or [])})"
        return "(unset)"
