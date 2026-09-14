"""war3map.imp — the editor's import list (files the World Editor keeps when saving)."""
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

DEFAULT_FLAG = 29  # most common flag in maps saved by the 2.x editor; bit meanings are undocumented


@dataclass
class ImportEntry:
    flag: int
    path: str  # as stored: '/' separators, no implicit prefix


@dataclass
class ImportList:
    version: int = 1
    entries: list[ImportEntry] = field(default_factory=list)
    trailing: bytes = b""


def parse(data: bytes) -> ImportList:
    r = Reader(data)
    version = r.i32()
    if version != 1:
        raise FormatError(f"unsupported import list version {version}")
    imports = ImportList(version)
    for _ in range(r.count(item_size=2)):
        imports.entries.append(ImportEntry(r.u8(), r.cstr()))
    imports.trailing = r.rest()
    return imports


def serialize(imports: ImportList) -> bytes:
    w = Writer()
    w.i32(imports.version)
    w.i32(len(imports.entries))
    for e in imports.entries:
        w.u8(e.flag)
        w.cstr(e.path)
    w.raw(imports.trailing)
    return w.getvalue()
