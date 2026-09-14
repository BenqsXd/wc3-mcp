"""Trigger structure: war3map.wtg as saved by the 1.31+ editor (marker 0x80000004, version 7).
Byte-exact on all 556 local maps. Parameter lists have no stored length, so parsing needs each GUI function's
parameter count from TriggerData."""
from collections.abc import Callable
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

MAGIC = b"WTG!"
FORMAT_MARKER = 0x80000004
PRESET, VARIABLE, FUNCTION, STRING, INVALID = 0, 1, 2, 3, -1
ROOT, LIBRARY, CATEGORY, TRIGGER, COMMENT, SCRIPT, VARIABLE_ELEMENT = 1, 2, 4, 8, 16, 32, 64
ID_PREFIX = {CATEGORY: 2, TRIGGER: 3, COMMENT: 4, VARIABLE_ELEMENT: 6}   # high byte of element ids

ArgCount = Callable[[int, str], "int | None"]


@dataclass
class Call:
    kind: int                                   # 0 event, 1 condition, 2 action, 3 call
    name: str
    params: list["Param"] | None = field(default_factory=list)   # None: the file stores no parameter list
    unknown: int = 0


@dataclass
class Param:
    type: int                                   # PRESET, VARIABLE, FUNCTION, STRING or INVALID
    value: str
    call: Call | None = None
    index: "Param | None" = None                # array index of a variable


@dataclass
class ECA:
    kind: int                                   # 0 event, 1 condition, 2 action
    name: str
    enabled: int = 1
    params: list[Param] = field(default_factory=list)
    children: list["ECA"] = field(default_factory=list)
    group: int = 0                              # block inside the parent (children only)


@dataclass
class Variable:
    name: str
    type: str
    unknown: int = 1
    is_array: int = 0
    array_size: int = 1
    initialized: int = 0
    initial: str = ""
    id: int = 0
    parent: int = 0


@dataclass
class Category:
    kind: int                                   # ROOT, LIBRARY or CATEGORY
    id: int
    name: str
    is_comment: int = 0
    expanded: int = 0
    parent: int = -1


@dataclass
class Trigger:
    kind: int                                   # TRIGGER, COMMENT or SCRIPT
    name: str
    description: str = ""
    is_comment: int = 0
    id: int = 0
    enabled: int = 1
    custom_text: int = 0
    initially_off: int = 0
    run_on_init: int = 0
    parent: int = 0
    ecas: list[ECA] = field(default_factory=list)


@dataclass
class VariableElement:
    id: int
    name: str
    parent: int = 0


@dataclass
class TriggerFile:
    version: int = 7
    counters: list[tuple[int, list[int]]] = field(default_factory=lambda: [(0, []) for _ in range(8)])
    definition_version: int = 2
    variables: list[Variable] = field(default_factory=list)
    elements: list = field(default_factory=list)   # Category | Trigger | VariableElement, parents first
    trailing: bytes = b""


def _count(count: ArgCount, kind: int, name: str) -> int:
    n = count(kind, name)
    if n is None:
        raise FormatError(f"unknown GUI function {name!r} (kind {kind}); the map may use a custom TriggerData")
    return n


def _param(r: Reader, count: ArgCount) -> Param:
    p = Param(r.i32(), r.cstr())
    if r.u32():
        call = Call(r.i32(), r.cstr())
        call.params = [_param(r, count) for _ in range(_count(count, call.kind, call.name))] if r.u32() else None
        call.unknown = r.u32()
        p.call = call
    if r.u32():
        p.index = _param(r, count)
    return p


def _eca(r: Reader, count: ArgCount, child: bool) -> ECA:
    e = ECA(r.i32(), "")
    if child:
        e.group = r.i32()
    e.name = r.cstr()
    e.enabled = r.u32()
    e.params = [_param(r, count) for _ in range(_count(count, e.kind, e.name))]
    e.children = [_eca(r, count, True) for _ in range(r.count(item_size=17))]
    return e


def parse(data: bytes, count: ArgCount) -> TriggerFile:
    r = Reader(data)
    if r.raw(4) != MAGIC:
        raise FormatError("not a trigger file (no WTG! header)")
    marker = r.u32()
    if marker != FORMAT_MARKER:
        raise FormatError(f"trigger format {marker:#x} is not supported (maps saved by editor 1.31+ only)")
    tf = TriggerFile(r.i32())
    if tf.version != 7:
        raise FormatError(f"trigger version {tf.version} is not supported")
    tf.counters = []
    for _ in range(8):
        n = r.i32()
        tf.counters.append((n, [r.i32() for _ in range(r.count(item_size=4))]))
    tf.definition_version = r.i32()
    for _ in range(r.count(item_size=27)):
        tf.variables.append(Variable(r.cstr(), r.cstr(), r.u32(), r.u32(), r.u32(), r.u32(), r.cstr(), r.i32(),
                                     r.i32()))
    for _ in range(r.count(item_size=13)):
        kind = r.u32()
        if kind in (ROOT, LIBRARY, CATEGORY):
            tf.elements.append(Category(kind, r.i32(), r.cstr(), r.u32(), r.u32(), r.i32()))
        elif kind in (TRIGGER, COMMENT, SCRIPT):
            t = Trigger(kind, r.cstr(), r.cstr(), r.u32(), r.i32(), r.u32(), r.u32(), r.u32(), r.u32(), r.i32())
            t.ecas = [_eca(r, count, False) for _ in range(r.count(item_size=13))]
            tf.elements.append(t)
        elif kind == VARIABLE_ELEMENT:
            tf.elements.append(VariableElement(r.i32(), r.cstr(), r.i32()))
        else:
            raise FormatError(f"unknown trigger element type {kind} at offset {r.pos - 4}")
    tf.trailing = r.rest()
    return tf


def _write_param(w: Writer, p: Param) -> None:
    w.i32(p.type)
    w.cstr(p.value)
    w.u32(p.call is not None)
    if p.call is not None:
        w.i32(p.call.kind)
        w.cstr(p.call.name)
        w.u32(p.call.params is not None)
        for sub in p.call.params or []:
            _write_param(w, sub)
        w.u32(p.call.unknown)
    w.u32(p.index is not None)
    if p.index is not None:
        _write_param(w, p.index)


def _write_eca(w: Writer, e: ECA, child: bool) -> None:
    w.i32(e.kind)
    if child:
        w.i32(e.group)
    w.cstr(e.name)
    w.u32(e.enabled)
    for p in e.params:
        _write_param(w, p)
    w.i32(len(e.children))
    for c in e.children:
        _write_eca(w, c, True)


def serialize(tf: TriggerFile) -> bytes:
    w = Writer()
    w.raw(MAGIC)
    w.u32(FORMAT_MARKER)
    w.i32(tf.version)
    for n, deleted in tf.counters:
        w.i32(n)
        w.i32(len(deleted))
        for d in deleted:
            w.i32(d)
    w.i32(tf.definition_version)
    w.i32(len(tf.variables))
    for v in tf.variables:
        w.cstr(v.name)
        w.cstr(v.type)
        for x in (v.unknown, v.is_array, v.array_size, v.initialized):
            w.u32(x)
        w.cstr(v.initial)
        w.i32(v.id)
        w.i32(v.parent)
    w.i32(len(tf.elements))
    for e in tf.elements:
        if isinstance(e, Category):
            w.u32(e.kind)
            w.i32(e.id)
            w.cstr(e.name)
            w.u32(e.is_comment)
            w.u32(e.expanded)
            w.i32(e.parent)
        elif isinstance(e, Trigger):
            w.u32(e.kind)
            w.cstr(e.name)
            w.cstr(e.description)
            w.u32(e.is_comment)
            w.i32(e.id)
            for x in (e.enabled, e.custom_text, e.initially_off, e.run_on_init):
                w.u32(x)
            w.i32(e.parent)
            w.i32(len(e.ecas))
            for x in e.ecas:
                _write_eca(w, x, False)
        else:
            w.u32(VARIABLE_ELEMENT)
            w.i32(e.id)
            w.cstr(e.name)
            w.i32(e.parent)
    w.raw(tf.trailing)
    return w.getvalue()
