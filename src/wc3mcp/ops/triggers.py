"""The Trigger Editor: war3map.wtg and war3map.wct as a tree, per-trigger JSON and text, and atomic edits."""
import re

from ..errors import ToolError
from ..formats import wct, wtg
from ..formats.binary import FormatError
from ..formats.wtg import CATEGORY, COMMENT, ROOT, TRIGGER, VARIABLE, Category, Trigger, Variable, VariableElement
from ..gamedata.triggerdata import ACTION, CONDITION, EVENT
from .gui import Checker, Renderer, eca_json, ecas_from_json, literal_text, script_name
from .strings import load_strings

SECTIONS = (("events", EVENT), ("conditions", CONDITION), ("actions", ACTION))


def _read(project, name: str) -> bytes | None:
    try:
        return project.read(name)
    except ToolError as e:
        if e.code != "no_such_file":
            raise
        return None


def _triggers(tf) -> list[Trigger]:
    return [e for e in tf.elements if isinstance(e, Trigger) and e.kind == TRIGGER]


def _root(tf) -> Category:
    return next((e for e in tf.elements if isinstance(e, Category) and e.kind == ROOT), Category(ROOT, 0, ""))


def _category_names(tf) -> dict[int, str]:
    return {e.id: e.name for e in tf.elements if isinstance(e, Category) and e.kind != ROOT}


def _load(project, td) -> tuple[wtg.TriggerFile, wct.CustomText]:
    data = _read(project, "war3map.wtg")
    if data is None:
        raise ToolError("no_triggers", "this map has no war3map.wtg (protected or script-only map)",
                        hint="map_file_read war3map.j or war3map.lua shows its script")
    text = _read(project, "war3map.wct")
    try:
        tf = wtg.parse(data, td.arg_count)
        ct = wct.parse(text) if text is not None else wct.CustomText()
    except FormatError as e:
        raise ToolError("bad_file", f"trigger data: {e}") from e
    count = len(_triggers(tf))
    if text is None:
        ct.texts = [None] * count
    elif len(ct.texts) != count:
        raise ToolError("bad_file", f"war3map.wct has {len(ct.texts)} trigger texts for {count} triggers")
    return tf, ct


def _type(t: Trigger) -> str:
    if t.kind == COMMENT or t.is_comment:
        return "comment"
    return "text" if t.custom_text else "gui"


def _find_trigger(tf, name) -> Trigger:
    t = next((e for e in tf.elements if isinstance(e, Trigger) and e.name == name), None)
    if t is None:
        raise ToolError("not_found", f"no trigger named {name!r}", hint="triggers_tree lists triggers")
    return t


def triggers_tree(project, catalog) -> dict:
    tf, ct = _load(project, catalog.trigger_data)
    names = _category_names(tf)
    categories, triggers = [], []
    for e in tf.elements:
        if isinstance(e, Category) and e.kind != ROOT:
            categories.append({"id": e.id, "name": e.name, "parent": names.get(e.parent), "comment": bool(e.is_comment)})
        elif isinstance(e, Trigger):
            triggers.append({"id": e.id, "name": e.name, "category": names.get(e.parent), "type": _type(e),
                             "enabled": bool(e.enabled), "initially_on": not e.initially_off,
                             "run_on_init": bool(e.run_on_init), "functions": len(e.ecas)})
    variables = []
    for v in tf.variables:
        item = {"name": v.name, "type": v.type, "category": names.get(v.parent)}
        if v.is_array:
            item["array_size"] = v.array_size
        if v.initialized:
            item["initial"] = v.initial
        variables.append(item)
    return {"map": _root(tf).name, "comment": ct.comment, "has_custom_script": bool(ct.header),
            "categories": categories, "triggers": triggers, "variables": variables}


def trigger_get(project, catalog, name: str | None = None) -> dict:
    td = catalog.trigger_data
    tf, ct = _load(project, td)
    if name is None:
        return {"type": "map", "name": _root(tf).name, "comment": ct.comment, "script": ct.header or ""}
    t = _find_trigger(tf, name)
    doc = {"id": t.id, "name": t.name, "category": _category_names(tf).get(t.parent), "description": t.description,
           "type": _type(t), "enabled": bool(t.enabled), "initially_on": not t.initially_off,
           "run_on_init": bool(t.run_on_init)}
    if doc["type"] == "text":
        doc["script"] = ct.texts[next(i for i, x in enumerate(_triggers(tf)) if x is t)] or ""
    elif doc["type"] == "gui":
        for key, kind in SECTIONS:
            doc[key] = [eca_json(e) for e in t.ecas if e.kind == kind]
        variables = {v.name: v for v in tf.variables}
        doc["text"] = "\n".join(Renderer(td, catalog, variables, load_strings(project)).lines(t.ecas))
    return doc


# ---- edits -----------------------------------------------------------------------------------------------------
COUNTER = {CATEGORY: 2, TRIGGER: 3, COMMENT: 4, wtg.VARIABLE_ELEMENT: 6}   # index into TriggerFile.counters
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
ALLOWED = {
    "category": {"name", "new_name", "parent", "comment"},
    "variable": {"name", "new_name", "type", "array_size", "initial", "category"},
    "trigger": {"name", "new_name", "category", "description", "enabled", "initially_on", "run_on_init", "events",
                "conditions", "actions", "script"},
    "delete": {"what", "name"},
    "header": {"script", "comment"},
}
SCRIPT_WARNING = "the map script is not regenerated yet: map_save (or script_build) rebuilds war3map.j or war3map.lua"
_HINT = ('ops: {"op": "category", "name": "Spawns"}, {"op": "variable", "name": "Count", "type": "integer"}, '
         '{"op": "trigger", "name": "Spawn", "events": [...], "actions": [...]} or {..., "script": "..."}, '
         '{"op": "delete", "what": "trigger", "name": "Spawn"}, {"op": "header", "script": "..."}')


def _all_params(ecas, enabled_only: bool = False):
    for e in ecas:
        if enabled_only and not e.enabled:
            continue
        stack = list(e.params)
        while stack:
            p = stack.pop()
            yield p
            if p.index is not None:
                stack.append(p.index)
            if p.call is not None:
                stack.extend(p.call.params or [])
        yield from _all_params(e.children, enabled_only)


def _editor_lines(text) -> str:
    """Custom script text with the Trigger Editor's CRLF line ends (the editor copies it into war3map.j verbatim)."""
    if not isinstance(text, str):
        raise ToolError("bad_value", "script must be text", hint=_HINT)
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def script_users(tf, ct, script: str) -> list[str]:
    """Triggers whose GUI parameters or custom script text use the global `script` ("map header" for the header)."""
    gui = [t.name for t in _triggers(tf) if any(p.type == VARIABLE and p.value == script for p in _all_params(t.ecas))]
    mention = re.compile(rf"\b{re.escape(script)}\b")
    texts = [(t.name, text) for t, text in zip(_triggers(tf), ct.texts) if text] + [("map header", ct.header or "")]
    return gui + [name for name, text in texts if mention.search(text)]


class _Edit:
    def __init__(self, project, catalog):
        self.project, self.catalog, self.td = project, catalog, catalog.trigger_data
        self.tf, self.ct = _load(project, self.td)
        self.before = (wtg.serialize(self.tf), wct.serialize(self.ct))
        self.text = {t.id: s for t, s in zip(_triggers(self.tf), self.ct.texts)}
        self.created: list[str] = []
        self.warnings: list[str] = []

    # lookups
    def _category(self, name, path: str) -> Category:
        found = [e for e in self.tf.elements if isinstance(e, Category) and e.kind == CATEGORY and e.name == name]
        if not found:
            raise ToolError("not_found", f"{path}: no category named {name!r}", hint="triggers_tree lists categories")
        if len(found) > 1:
            raise ToolError("ambiguous", f"{path}: {len(found)} categories are named {name!r}", hint="rename one first")
        return found[0]

    def _first_category(self, path: str) -> Category:
        c = next((e for e in self.tf.elements if isinstance(e, Category) and e.kind == CATEGORY), None)
        if c is None:
            raise ToolError("bad_op", f"{path}: the map has no trigger category yet; create one first", hint=_HINT)
        return c

    def _variable(self, name) -> Variable | None:
        return next((v for v in self.tf.variables if v.name == name), None)

    def _variable_element(self, v: Variable) -> VariableElement | None:
        return next((e for e in self.tf.elements if isinstance(e, VariableElement) and e.id == v.id), None)

    def _trigger(self, name) -> Trigger | None:
        return next((e for e in _triggers(self.tf) if e.name == name), None)

    def _users(self, variable_name: str, skip=None) -> list[str]:
        return [t.name for t in _triggers(self.tf) if t is not skip
                and any(p.type == VARIABLE and p.value == variable_name for p in _all_params(t.ecas))]

    def _rename_references(self, old: str, new: str) -> None:
        for t in _triggers(self.tf):
            for p in _all_params(t.ecas):
                if p.type == VARIABLE and p.value == old:
                    p.value = new
        if any(old in (s or "") for s in [self.ct.header, *self.text.values()]):
            self.warnings.append(f"custom script text still mentions {old}; update it by hand")

    # element order and ids
    def _new_id(self, kind: int) -> int:
        i, prefix = COUNTER[kind], wtg.ID_PREFIX[kind]
        n, deleted = self.tf.counters[i]
        used = [e.id & 0xFFFFFF for e in [*self.tf.elements, *self.tf.variables] if (e.id >> 24) == prefix]
        low = max([n] + [u + 1 for u in used])
        self.tf.counters[i] = (low + 1, deleted)
        return (prefix << 24) | low

    def _remove(self, element, kind: int) -> None:
        self.tf.elements = [e for e in self.tf.elements if e is not element]
        n, deleted = self.tf.counters[COUNTER[kind]]
        self.tf.counters[COUNTER[kind]] = (n, deleted + [element.id & 0xFFFFFF])

    def _subtree(self, element_id: int) -> set[int]:
        ids = {element_id}
        for e in self.tf.elements:  # parents precede children
            if e.parent in ids:
                ids.add(e.id)
        return ids

    def _place(self, elements: list, parent_id: int) -> None:
        block = self._subtree(parent_id)
        at = max((i for i, e in enumerate(self.tf.elements) if e.id in block), default=len(self.tf.elements) - 1) + 1
        self.tf.elements[at:at] = elements

    def _move(self, element, parent_id: int, path: str) -> None:
        moving_ids = self._subtree(element.id)
        if parent_id in moving_ids:
            raise ToolError("bad_op", f"{path}: a category cannot move into itself", hint=_HINT)
        moving = [e for e in self.tf.elements if e.id in moving_ids]
        self.tf.elements = [e for e in self.tf.elements if e.id not in moving_ids]
        element.parent = parent_id
        self._place(moving, parent_id)

    # ops
    def op_category(self, op: dict, path: str) -> None:
        name = op.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolError("bad_op", f"{path}: name is required", hint=_HINT)
        exists = any(isinstance(e, Category) and e.kind == CATEGORY and e.name == name for e in self.tf.elements)
        parent_id = _root(self.tf).id
        if op.get("parent") is not None:
            parent_id = self._category(op["parent"], f"{path}.parent").id
        if exists:
            c = self._category(name, path)
            if "parent" in op and c.parent != parent_id:
                self._move(c, parent_id, path)
        else:
            c = Category(CATEGORY, self._new_id(CATEGORY), name, parent=parent_id)
            self._place([c], parent_id)
            self.created.append(name)
        if "comment" in op:
            c.is_comment = int(bool(op["comment"]))
        if "new_name" in op:
            new = op["new_name"]
            if not isinstance(new, str) or not new.strip():
                raise ToolError("bad_value", f"{path}: new_name must be a non-empty name", path=f"{path}.new_name")
            c.name = new

    def op_variable(self, op: dict, path: str) -> None:
        name = op.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ToolError("bad_value", f"{path}: variable names start with a letter and use letters, digits and _",
                            path=f"{path}.name")
        v = self._variable(name)
        if v is None:
            if "type" not in op:
                raise ToolError("bad_op", f"{path}: type is required for a new variable", hint=_HINT)
            category = self._category(op["category"], f"{path}.category") if "category" in op else self._first_category(path)
            v = Variable(name, "", id=self._new_id(wtg.VARIABLE_ELEMENT), parent=category.id)
            self.tf.variables.append(v)
            self._place([VariableElement(v.id, name, category.id)], category.id)
            self.created.append(name)
        elif "category" in op:
            category = self._category(op["category"], f"{path}.category")
            v.parent = category.id
            element = self._variable_element(v)
            if element is not None:
                self._move(element, category.id, path)
        if "type" in op:
            t = self.td.types.get(op["type"]) if isinstance(op["type"], str) else None
            if t is None or not t.global_ok:
                raise ToolError("bad_value", f"{path}: {op['type']!r} is not a variable type",
                                hint="data_search kind=trigger_type lists types", path=f"{path}.type")
            v.type = t.name
        if "array_size" in op:
            size = op["array_size"]
            if size is not None and (not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 32768):
                raise ToolError("bad_value", f"{path}: array_size must be 1-32768 or null", path=f"{path}.array_size")
            v.is_array, v.array_size = (1, size) if size else (0, 1)
        if "initial" in op:
            text = "" if op["initial"] is None else literal_text(op["initial"])
            if text is None:
                raise ToolError("bad_value", f"{path}: initial must be a literal", path=f"{path}.initial")
            v.initial, v.initialized = text, int(text != "")
        if v.initialized:
            checker = Checker(self.td, {}, set())
            checker.literal(v.initial, v.type, f"{path}.initial")
            if checker.errors:
                raise ToolError("bad_value", checker.errors[0], path=f"{path}.initial")
        if "new_name" in op:
            new = op["new_name"]
            if not isinstance(new, str) or not NAME_RE.match(new):
                raise ToolError("bad_value", f"{path}: new_name is not a valid variable name", path=f"{path}.new_name")
            if self._variable(new) is not None:
                raise ToolError("name_taken", f"{path}: a variable named {new!r} already exists")
            self._rename_references(v.name, new)
            element = self._variable_element(v)
            if element is not None:
                element.name = new
            v.name = new

    def _check_trigger_name(self, name, current, path: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ToolError("bad_value", f"{path}: trigger names must be non-empty text", path=path)
        if any(t is not current and script_name(t.name) == script_name(name) for t in _triggers(self.tf)):
            raise ToolError("name_taken", f"{path}: trigger {name!r} clashes with an existing trigger name",
                            hint="names that differ only in spaces or punctuation share one script name")

    def op_trigger(self, op: dict, path: str) -> None:
        name = op.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolError("bad_op", f"{path}: name is required", hint=_HINT)
        sections = [key for key, _ in SECTIONS if key in op]
        if "script" in op and sections:
            raise ToolError("bad_op", f"{path}: give either script or events/conditions/actions", hint=_HINT)
        t = self._trigger(name)
        if t is None:
            self._check_trigger_name(name, None, path)
            category = self._category(op["category"], f"{path}.category") if "category" in op else self._first_category(path)
            t = Trigger(TRIGGER, name, id=self._new_id(TRIGGER), parent=category.id)
            self._place([t], category.id)
            self.text[t.id] = None
            self.created.append(name)
        elif "category" in op:
            self._move(t, self._category(op["category"], f"{path}.category").id, path)
        if "description" in op:
            if not isinstance(op["description"], str):
                raise ToolError("bad_value", f"{path}: description must be text", path=f"{path}.description")
            t.description = op["description"]
        for key, attr, invert in (("enabled", "enabled", False), ("initially_on", "initially_off", True),
                                  ("run_on_init", "run_on_init", False)):
            if key in op:
                if not isinstance(op[key], bool):
                    raise ToolError("bad_value", f"{path}: {key} must be true or false", path=f"{path}.{key}")
                setattr(t, attr, int(op[key] != invert))
        if "script" in op:
            if not isinstance(op["script"], str):
                raise ToolError("bad_value", f"{path}: script must be text", path=f"{path}.script")
            t.custom_text, t.ecas, self.text[t.id] = 1, [], _editor_lines(op["script"])
        elif sections:
            variables = {v.name: v for v in self.tf.variables}
            current = {key: ([] if t.custom_text else [e for e in t.ecas if e.kind == kind]) for key, kind in SECTIONS}
            for key, kind in SECTIONS:
                if key in op:
                    current[key] = ecas_from_json(op[key], kind, self.td, variables, f"{path}.{key}")
            checker = Checker(self.td, variables, {script_name(x.name) for x in _triggers(self.tf)})
            for key, _ in SECTIONS:
                checker.ecas(current[key], f"{path}.{key}")
            if checker.errors:
                raise ToolError("invalid_trigger", f"{path}: {len(checker.errors)} problem(s), first: {checker.errors[0]}",
                                hint="data_get kind=trigger_function shows argument types", errors=checker.errors[:20])
            self.warnings += checker.warnings
            t.ecas = current["events"] + current["conditions"] + current["actions"]
            t.custom_text, self.text[t.id] = 0, None
        if "new_name" in op:
            self._check_trigger_name(op["new_name"], t, f"{path}.new_name")
            self._rename_references("gg_trg_" + script_name(t.name), "gg_trg_" + script_name(op["new_name"]))
            t.name = op["new_name"]

    def op_delete(self, op: dict, path: str) -> None:
        what, name = op.get("what"), op.get("name")
        if what == "variable":
            v = self._variable(name)
            if v is None:
                raise ToolError("not_found", f"{path}: no variable named {name!r}", hint="triggers_tree lists variables")
            users = self._users(v.name)
            if users:
                raise ToolError("in_use", f"{path}: variable {name!r} is used by {len(users)} trigger(s)",
                                hint="change those triggers first", triggers=users[:20])
            self.tf.variables = [x for x in self.tf.variables if x is not v]
            element = self._variable_element(v)
            if element is not None:
                self._remove(element, wtg.VARIABLE_ELEMENT)
        elif what == "trigger":
            t = self._trigger(name)
            if t is None:
                raise ToolError("not_found", f"{path}: no trigger named {name!r}", hint="triggers_tree lists triggers")
            users = self._users("gg_trg_" + script_name(t.name), skip=t)
            if users:
                raise ToolError("in_use", f"{path}: trigger {name!r} is used by {len(users)} trigger(s)",
                                hint="change those triggers first", triggers=users[:20])
            self._remove(t, TRIGGER)
            self.text.pop(t.id, None)
        elif what == "category":
            c = self._category(name, path)
            children = [e for e in self.tf.elements if e.parent == c.id]
            if children:
                raise ToolError("not_empty", f"{path}: category {name!r} still holds {len(children)} item(s)",
                                hint="move or delete them first")
            self._remove(c, CATEGORY)
        else:
            raise ToolError("bad_op", f'{path}: what must be "trigger", "category" or "variable"', hint=_HINT)

    def op_header(self, op: dict, path: str) -> None:
        for key in ("script", "comment"):
            if key in op and not isinstance(op[key], str):
                raise ToolError("bad_value", f"{path}: {key} must be text", path=f"{path}.{key}")
        if "script" in op:
            self.ct.header = _editor_lines(op["script"]) if op["script"] else None
        if "comment" in op:
            self.ct.comment = op["comment"]

    def finish(self) -> dict:
        self.ct.texts = [self.text.get(t.id) for t in _triggers(self.tf)]
        data, text = wtg.serialize(self.tf), wct.serialize(self.ct)
        if data != self.before[0]:
            self.project.write("war3map.wtg", data)
        if text != self.before[1]:
            self.project.write("war3map.wct", text)
        changed = (data, text) != self.before
        if changed:
            self.warnings.append(SCRIPT_WARNING)
        return {"changed": changed, "created": self.created, "warnings": self.warnings}


def triggers_edit(project, catalog, ops: list) -> dict:
    edit = _Edit(project, catalog)
    for i, op in enumerate(ops):
        path = f"ops[{i}]"
        try:
            action = op.get("op") if isinstance(op, dict) else None
            if action not in ALLOWED:
                raise ToolError("bad_op", f"{path}: unknown op {action!r}", hint=_HINT)
            extra = set(op) - {"op"} - ALLOWED[action]
            if extra:
                raise ToolError("bad_op", f"{path}: unknown keys {sorted(extra)}", hint=_HINT)
            getattr(edit, f"op_{action}")(op, path)
        except ToolError as e:
            e.details.setdefault("op_index", i)
            raise
    return edit.finish()
