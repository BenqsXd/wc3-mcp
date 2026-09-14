"""The Trigger Editor: war3map.wtg and war3map.wct as a tree, per-trigger JSON and text, and atomic edits."""
from ..errors import ToolError
from ..formats import wct, wtg
from ..formats.binary import FormatError
from ..formats.wtg import COMMENT, ROOT, TRIGGER, Category, Trigger
from ..gamedata.triggerdata import ACTION, CONDITION, EVENT
from .gui import Renderer, eca_json
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
