"""Custom script text: war3map.wct as saved by the 1.31+ editor (marker 0x80000004, version 1)."""
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

FORMAT_MARKER = 0x80000004


@dataclass
class CustomText:
    version: int = 1
    comment: str = ""
    header: str | None = None                               # the map's custom script code; None when empty
    texts: list[str | None] = field(default_factory=list)   # one per TRIGGER element of war3map.wtg, in order


def _sized(r: Reader) -> str | None:
    size = r.u32()
    if size == 0:
        return None
    data = r.raw(size)
    if data[-1:] != b"\0":
        raise FormatError(f"custom text ending at offset {r.pos} is not NUL-terminated")
    return data[:-1].decode("utf-8", "surrogateescape")


def parse(data: bytes) -> CustomText:
    r = Reader(data)
    marker = r.u32()
    if marker != FORMAT_MARKER:
        raise FormatError(f"custom text format {marker:#x} is not supported (maps saved by editor 1.31+ only)")
    ct = CustomText(r.i32(), r.cstr())
    if ct.version != 1:
        raise FormatError(f"custom text version {ct.version} is not supported")
    ct.header = _sized(r)
    while r.pos < len(r.data):
        ct.texts.append(_sized(r))
    return ct


def _write_sized(w: Writer, text: str | None) -> None:
    if text is None:
        w.u32(0)
        return
    data = text.encode("utf-8", "surrogateescape") + b"\0"
    w.u32(len(data))
    w.raw(data)


def serialize(ct: CustomText) -> bytes:
    w = Writer()
    w.u32(FORMAT_MARKER)
    w.i32(ct.version)
    w.cstr(ct.comment)
    _write_sized(w, ct.header)
    for text in ct.texts:
        _write_sized(w, text)
    return w.getvalue()
