"""war3map.w3c — cameras placed in the editor (gg_cam_ camera setups)."""
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

VERSIONS = (0, 3)
FIELDS_V0 = ("x", "y", "z_offset", "rotation", "angle_of_attack", "distance", "roll", "field_of_view", "far_z",
             "near_z", "local_pitch", "local_yaw", "local_roll")
FIELDS_V3 = FIELDS_V0 + ("depth_of_field_distance", "depth_of_field_scale", "z_absolute")


@dataclass
class Camera:
    name: str
    values: dict[str, float]
    camera_type: int = 0  # v3+


@dataclass
class CameraFile:
    version: int = 0
    cameras: list[Camera] = field(default_factory=list)


def fields(version: int) -> tuple[str, ...]:
    if version not in VERSIONS:
        raise FormatError(f"unsupported cameras version {version}")
    return FIELDS_V3 if version >= 3 else FIELDS_V0


def parse(data: bytes) -> CameraFile:
    r = Reader(data)
    cf = CameraFile(r.i32())
    names = fields(cf.version)
    for _ in range(r.count(item_size=4 * len(names) + 1)):
        values = {n: r.f32() for n in names}
        cf.cameras.append(Camera(r.cstr(), values, r.i32() if cf.version >= 3 else 0))
    r.done()
    return cf


def serialize(cf: CameraFile) -> bytes:
    names = fields(cf.version)
    w = Writer()
    w.i32(cf.version)
    w.i32(len(cf.cameras))
    for cam in cf.cameras:
        missing = [n for n in names if n not in cam.values]
        if missing:
            raise FormatError(f"camera {cam.name!r} has no value for {', '.join(missing)}")
        for n in names:
            w.f32(cam.values[n])
        w.cstr(cam.name)
        if cf.version >= 3:
            w.i32(cam.camera_type)
    return w.getvalue()
