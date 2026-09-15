"""war3campaign.w3f — campaign info (format version 3, the Reforged Campaign Editor): text, minimap, loading screen,
fog, the campaign screen buttons and the campaign's maps."""
import struct
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

VERSION = 3
FLAG_VARIABLE_DIFFICULTY, FLAG_IMPORTED_AMBIENT, FLAG_MINIMAP_FROM_MAP = 1, 2, 4
BUTTON_VISIBLE, BUTTON_CINEMATIC = 1, 2


def _float(hex_bytes: str) -> float:
    return struct.unpack("<f", bytes.fromhex(hex_bytes))[0]


# a new campaign's fog floats hold these values (uninitialised in the editor); the UI shows them as 0.00
_Z_DEFAULT, _DEFAULT = _float("000408ff"), _float("000000ff")
FOG_FLOATS = ("fog_z_start", "fog_z_end", "fog_density")
FOG_FLOATS_2 = ("fog_height_start", "fog_height_end", "fog_linear_start", "fog_linear_end", "fog_max_opacity")


@dataclass
class Button:
    flags: int
    chapter: str
    title: str
    map: str


@dataclass
class CampaignMap:
    unknown: str
    path: str


@dataclass
class CampaignInfo:
    version: int = VERSION
    campaign_version: int = 1
    editor_version: int = 7000
    name: str = "Just another Warcraft III campaign"
    difficulty: str = "Normal"
    author: str = "Unknown"
    description: str = "Nondescript"
    flags: int = 0
    background: int = -1
    background_path: str = ""
    minimap_path: str = ""
    ambient_sound: int = -1
    ambient_sound_path: str = ""
    fog_style: int = -1
    fog_z_start: float = _Z_DEFAULT
    fog_z_end: float = _Z_DEFAULT
    fog_density: float = _DEFAULT
    fog_color: bytes = b"\0\0\0\0"          # B, G, R, A
    cursor: int = 0
    fog_height_start: float = _DEFAULT
    fog_height_end: float = _DEFAULT
    fog_linear_start: float = _DEFAULT
    fog_linear_end: float = _DEFAULT
    fog_max_opacity: float = _DEFAULT
    fog_over_sky: int = 0
    background_version: int = 0
    buttons: list[Button] = field(default_factory=list)
    maps: list[CampaignMap] = field(default_factory=list)


def parse(data: bytes) -> CampaignInfo:
    r = Reader(data)
    version = r.i32()
    if version != VERSION:
        raise FormatError(f"campaign info version {version} is not supported (only {VERSION}, the current editor's)")
    ci = CampaignInfo(version, r.i32(), r.i32(), r.cstr(), r.cstr(), r.cstr(), r.cstr(), r.i32(), r.i32(), r.cstr(),
                      r.cstr(), r.i32(), r.cstr(), r.i32())
    for name in FOG_FLOATS:
        setattr(ci, name, r.f32())
    ci.fog_color, ci.cursor = r.raw(4), r.i32()
    for name in FOG_FLOATS_2:
        setattr(ci, name, r.f32())
    ci.fog_over_sky, ci.background_version = r.i32(), r.i32()
    for _ in range(r.count(item_size=7)):
        ci.buttons.append(Button(r.i32(), r.cstr(), r.cstr(), r.cstr()))
    for _ in range(r.count(item_size=2)):
        ci.maps.append(CampaignMap(r.cstr(), r.cstr()))
    r.done()
    return ci


def serialize(ci: CampaignInfo) -> bytes:
    if ci.version != VERSION:
        raise FormatError(f"campaign info version {ci.version} cannot be written (only {VERSION})")
    if len(ci.fog_color) != 4:
        raise FormatError("fog_color must be 4 bytes (B, G, R, A)")
    w = Writer()
    for v in (ci.version, ci.campaign_version, ci.editor_version):
        w.i32(v)
    for s in (ci.name, ci.difficulty, ci.author, ci.description):
        w.cstr(s)
    w.i32(ci.flags)
    w.i32(ci.background)
    w.cstr(ci.background_path)
    w.cstr(ci.minimap_path)
    w.i32(ci.ambient_sound)
    w.cstr(ci.ambient_sound_path)
    w.i32(ci.fog_style)
    for name in FOG_FLOATS:
        w.f32(getattr(ci, name))
    w.raw(ci.fog_color)
    w.i32(ci.cursor)
    for name in FOG_FLOATS_2:
        w.f32(getattr(ci, name))
    w.i32(ci.fog_over_sky)
    w.i32(ci.background_version)
    w.i32(len(ci.buttons))
    for b in ci.buttons:
        w.i32(b.flags)
        for s in (b.chapter, b.title, b.map):
            w.cstr(s)
    w.i32(len(ci.maps))
    for m in ci.maps:
        w.cstr(m.unknown)
        w.cstr(m.path)
    return w.getvalue()
