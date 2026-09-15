"""war3map.w3s — sounds defined in the Sound Editor (gg_snd_ variables)."""
import struct
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

VERSIONS = (3,)
UNSET = 4294967296.0  # f32 0x4F800000, the editor's "use the default" value
BASE_FIELDS = ("flags", "fade_in", "fade_out", "volume", "pitch", "pitch_variance", "priority", "channel",
               "min_distance", "max_distance", "distance_cutoff", "cone_inside", "cone_outside", "cone_outside_volume",
               "cone_x", "cone_y", "cone_z")
_BASE = struct.Struct("<Iiiiffiifffffifff")
TAIL_FIELDS = (("name2", str), ("label", str), ("path2", str), ("dialogue_text_key", int), ("unknown_s1", str),
               ("dialogue_speaker_key", int), ("unknown_s2", str), ("unknown_i1", int), ("speaker_unit", str),
               ("facial_animation_label", str), ("facial_animation_group_label", str),
               ("facial_animation_set_path", str), ("unknown_i2", int))


@dataclass
class Sound:
    name: str
    path: str
    eax: str = "DefaultEAXON"
    flags: int = 4  # 1 looping, 2 3D, 4 stop when out of range, 8 music
    fade_in: int = 10
    fade_out: int = 10
    volume: int = 127
    pitch: float = UNSET
    pitch_variance: float = UNSET
    priority: int = 8
    channel: int = -1
    min_distance: float = UNSET
    max_distance: float = UNSET
    distance_cutoff: float = UNSET
    cone_inside: float = UNSET
    cone_outside: float = UNSET
    cone_outside_volume: int = 0
    cone_x: float = UNSET
    cone_y: float = UNSET
    cone_z: float = UNSET
    name2: str | None = None  # written again after the base fields; None = same as name
    label: str = ""
    path2: str | None = None  # None = same as path
    dialogue_text_key: int = -1  # TRIGSTR number
    unknown_s1: str = ""
    dialogue_speaker_key: int = -1
    unknown_s2: str = ""
    unknown_i1: int = 0
    speaker_unit: str = ""
    facial_animation_label: str = ""
    facial_animation_group_label: str = ""
    facial_animation_set_path: str = ""
    unknown_i2: int = 1


@dataclass
class SoundFile:
    version: int = 3
    sounds: list[Sound] = field(default_factory=list)


def _check(version: int) -> None:
    if version not in VERSIONS:
        raise FormatError(f"unsupported sounds version {version}")


def parse(data: bytes) -> SoundFile:
    r = Reader(data)
    sf = SoundFile(r.i32())
    _check(sf.version)
    for _ in range(r.count(item_size=96)):
        s = Sound(r.cstr(), r.cstr(), r.cstr(), *_BASE.unpack(r.raw(_BASE.size)))
        for name, kind in TAIL_FIELDS:
            setattr(s, name, r.cstr() if kind is str else r.i32())
        s.name2 = None if s.name2 == s.name else s.name2
        s.path2 = None if s.path2 == s.path else s.path2
        sf.sounds.append(s)
    r.done()
    return sf


def serialize(sf: SoundFile) -> bytes:
    _check(sf.version)
    w = Writer()
    w.i32(sf.version)
    w.i32(len(sf.sounds))
    for s in sf.sounds:
        for text in (s.name, s.path, s.eax):
            w.cstr(text)
        w.raw(_BASE.pack(*(getattr(s, f) for f in BASE_FIELDS)))
        repeats = {"name2": s.name, "path2": s.path}
        for name, kind in TAIL_FIELDS:
            value = getattr(s, name)
            value = repeats[name] if value is None else value
            if kind is str:
                w.cstr(value)
            else:
                w.i32(value)
    return w.getvalue()
