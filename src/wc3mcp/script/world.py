"""Editor-generated script parts for regions, cameras and sounds: InitSounds, CreateRegions, CreateCameras and their
gg_rct_ / gg_cam_ / gg_snd_ globals. Exact on the local JASS corpus except a few dialogue sounds whose key lines the
editor left out inconsistently."""
import re
import struct
from dataclasses import dataclass
from typing import Callable

from ..formats import w3c, w3e, w3r, w3s
from ..formats.wts import TriggerStrings
from ..ops.gui import script_name

UNSET = w3s.UNSET
MUSIC = 8
CAMERA_FIELDS = (("z_offset", "ZOFFSET"), ("rotation", "ROTATION"), ("angle_of_attack", "ANGLE_OF_ATTACK"),
                 ("distance", "TARGET_DISTANCE"), ("roll", "ROLL"), ("field_of_view", "FIELD_OF_VIEW"), ("far_z", "FARZ"),
                 ("near_z", "NEARZ"), ("local_pitch", "LOCAL_PITCH"), ("local_yaw", "LOCAL_YAW"),
                 ("local_roll", "LOCAL_ROLL"), ("depth_of_field_distance", "DEPTH_OF_FIELD_DISTANCE"),
                 ("depth_of_field_scale", "DEPTH_OF_FIELD_SCALE"), ("z_absolute", "ZABSOLUTE"))
_CREATE = re.compile(r'^    set (gg_snd_\w+) = CreateSound\( ("(?:[^"\\]|\\.)*"),', re.M)
_DURATION = re.compile(r"^    call SetSoundDuration\( (gg_snd_\w+), (\d+) \)", re.M)
_POSITION = re.compile(r"^    call SetSoundPosition\( (gg_snd_\w+), ([-\d.]+), ([-\d.]+), ([-\d.]+) \)", re.M)


@dataclass
class World:
    regions: w3r.RegionFile | None
    cameras: w3c.CameraFile | None
    sounds: w3s.SoundFile | None
    terrain: w3e.Terrain | None
    strings: TriggerStrings
    label_row: Callable[[str], dict | None]  # SoundInfo SLK row of a sound label
    audio: Callable[[str], bytes | None]  # sound file bytes (map or game data)


def _f(v: float) -> str:
    return f"{v:.1f}"


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _slk(row: dict | None, column: str) -> float | None:
    try:
        return float((row or {}).get(column))
    except (TypeError, ValueError):
        return None


def _function(name: str, lines: list[str]) -> str:
    return f"function {name} takes nothing returns nothing\n" + "".join(x + "\n" for x in lines) + "endfunction\n"


# ---- audio length ----------------------------------------------------------------------------------------------
_MP3_BITRATES = {1: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
                 2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)}
_MP3_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def _wav(data: bytes) -> tuple[int, int]:
    p, rate, align, size = 12, 0, 1, 0
    while p + 8 <= len(data):
        chunk, n = data[p:p + 4], struct.unpack_from("<I", data, p + 4)[0]
        if chunk == b"fmt ":
            rate, align = struct.unpack_from("<I", data, p + 12)[0], struct.unpack_from("<H", data, p + 20)[0]
        elif chunk == b"data":
            size = n
        p += 8 + n + (n & 1)
    return size // max(align, 1), rate


def _mp3(data: bytes) -> tuple[int, int]:
    p = 10 + ((data[6] & 127) << 21 | (data[7] & 127) << 14 | (data[8] & 127) << 7 | (data[9] & 127)) \
        if data[:3] == b"ID3" else 0
    samples = rate = 0
    while p + 4 <= len(data):
        h = int.from_bytes(data[p:p + 4], "big")
        version, bitrate, rate_index = (h >> 19) & 3, (h >> 12) & 15, (h >> 10) & 3
        if h >> 21 != 0x7FF or version == 1 or (h >> 17) & 3 != 1 or bitrate in (0, 15) or rate_index == 3:
            p += 1
            continue
        rate = _MP3_RATES[version][rate_index]
        mpeg1 = version == 3
        samples += 1152 if mpeg1 else 576
        p += (144 if mpeg1 else 72) * _MP3_BITRATES[1 if mpeg1 else 2][bitrate] * 1000 // rate + ((h >> 9) & 1)
    return samples - 529, rate  # decoder delay


def audio_ms(data: bytes) -> int | None:
    """Length in ms of Ogg Vorbis, FLAC, WAV or MP3 data, or None when it cannot be read.
    ponytail: matches the editor's SetSoundDuration for most game sounds; voice lines with several shipped variants
    can differ by ±500 ms. The splice reuses durations already in the script for unchanged sounds."""
    try:
        if data[:4] == b"OggS":
            i = data.find(b"\x01vorbis")
            samples, rate = struct.unpack_from("<q", data, data.rfind(b"OggS") + 6)[0], struct.unpack_from("<I", data, i + 12)[0]
        elif data[:4] == b"fLaC":
            info = data[8:42]
            samples, rate = (info[13] & 15) << 32 | int.from_bytes(info[14:18], "big"), int.from_bytes(info[10:13], "big") >> 4
        elif data[:4] == b"RIFF":
            samples, rate = _wav(data)
        else:
            samples, rate = _mp3(data)
        return int(samples * 1000 / rate) if rate and samples >= 0 else None
    except (struct.error, IndexError, KeyError):
        return None


# ---- sections --------------------------------------------------------------------------------------------------
def global_decls(regions, cameras, sounds) -> list[tuple[str, str, str | None]]:
    out = [("rect", "gg_rct_" + script_name(g.name), "null") for g in (regions.regions if regions else [])]
    out += [("camerasetup", "gg_cam_" + script_name(c.name), "null") for c in (cameras.cameras if cameras else [])]
    out += [("string", s.name, None) if s.flags & MUSIC else ("sound", s.name, "null")
            for s in (sounds.sounds if sounds else [])]
    first = {}
    for decl in out:
        first.setdefault(decl[1], decl)  # one declaration per name, at its first position
    return list(first.values())


def create_regions(rf: w3r.RegionFile, terrain: w3e.Terrain | None, positions: dict) -> str:
    lines = ["    local weathereffect we", ""]
    for g in rf.regions:
        var = "gg_rct_" + script_name(g.name)
        lines.append(f"    set {var} = Rect( {_f(g.left)}, {_f(g.bottom)}, {_f(g.right)}, {_f(g.top)} )")
        if g.weather != w3r.NO_ID:
            lines += [f"    set we = AddWeatherEffect( {var}, '{g.weather.decode('latin-1')}' )",
                      "    call EnableWeatherEffect( we, true )"]
        if g.ambient_sound:
            x, y = _f((g.left + g.right) / 2), _f((g.bottom + g.top) / 2)
            z = positions.get((g.ambient_sound, x, y))
            if z is None:
                z = _f(w3e.ground_height(terrain, (g.left + g.right) / 2, (g.bottom + g.top) / 2)) if terrain else "0.0"
            lines += [f"    call SetSoundPosition( {g.ambient_sound}, {x}, {y}, {z} )",
                      f"    call RegisterStackedSound( {g.ambient_sound}, true, {_f(g.right - g.left)}, "
                      f"{_f(g.top - g.bottom)} )"]
    return _function("CreateRegions", lines)


def create_cameras(cf: w3c.CameraFile) -> str:
    lines = []
    for c in cf.cameras:
        var = "gg_cam_" + script_name(c.name)
        lines += ["", f"    set {var} = CreateCameraSetup(  )"]
        lines += [f"    call CameraSetupSetField( {var}, CAMERA_FIELD_{field}, {_f(c.values[key])}, 0.0 )"
                  for key, field in CAMERA_FIELDS if key in c.values]
        lines.append(f"    call CameraSetupSetDestPosition( {var}, {_f(c.values['x'])}, {_f(c.values['y'])}, 0.0 )")
        if cf.version >= 3:
            lines.append(f"    call BlzCameraSetupSetCameraType( {var}, {c.camera_type} )")
    return _function("CreateCameras", lines + [""])


def _sound_lines(s: w3s.Sound, world: World, duration: int) -> list[str]:
    v, flag = s.name, lambda bit: "true" if s.flags & bit else "false"
    if s.flags & MUSIC:
        return [f"set {v} = {_q(s.path)}"]
    out = [f"set {v} = CreateSound( {_q(s.path)}, {flag(1)}, {flag(2)}, {flag(4)}, {s.fade_in}, {s.fade_out}, "
           f"{_q(s.eax)} )"]
    row = world.label_row(s.label) if s.label else None
    if s.label:
        out.append(f"call SetSoundParamsFromLabel( {v}, {_q(s.label)} )")
    if s.facial_animation_group_label or s.facial_animation_set_path:
        out += [f"call SetSoundFacialAnimationLabel( {v}, {_q(s.facial_animation_label)} )",
                f"call SetSoundFacialAnimationGroupLabel( {v}, {_q(s.facial_animation_group_label)} )",
                f"call SetSoundFacialAnimationSetFilepath( {v}, {_q(s.facial_animation_set_path)} )"]
    for key, fn in ((s.dialogue_speaker_key, "SetDialogueSpeakerNameKey"), (s.dialogue_text_key, "SetDialogueTextKey")):
        if key >= 0 and world.strings.get(key) is not None:
            out.append(f'call {fn}( {v}, "TRIGSTR_{key}" )')
    out.append(f"call SetSoundDuration( {v}, {duration} )")
    labelled = bool(s.label)  # a label supplies defaults: only differing values are written
    channel = max(s.channel, 0)
    if not labelled or channel != _slk(row, "Channel"):
        out.append(f"call SetSoundChannel( {v}, {channel} )")
    out.append(f"call SetSoundVolume( {v}, {s.volume} )")
    pitch = 1.0 if s.pitch == UNSET else s.pitch
    if not labelled or pitch != _slk(row, "Pitch"):
        out.append(f"call SetSoundPitch( {v}, {_f(pitch)} )")
    if s.flags & 2:
        near = 0.0 if s.min_distance == UNSET else s.min_distance
        far = 10000.0 if s.max_distance == UNSET else s.max_distance
        if not labelled or (near, far) != (_slk(row, "MinDistance"), _slk(row, "MaxDistance")):
            out.append(f"call SetSoundDistances( {v}, {_f(near)}, {_f(far)} )")
        cutoff = 3000.0 if s.distance_cutoff == UNSET else s.distance_cutoff
        if not labelled or cutoff != _slk(row, "DistanceCutoff"):
            out.append(f"call SetSoundDistanceCutoff( {v}, {_f(cutoff)} )")
        if not labelled or not (s.cone_inside == UNSET and s.cone_outside == UNSET and s.cone_outside_volume == -1):
            inside = 0.0 if s.cone_inside == UNSET else s.cone_inside
            outside = 0.0 if s.cone_outside == UNSET else s.cone_outside
            out.append(f"call SetSoundConeAngles( {v}, {_f(inside)}, {_f(outside)}, {s.cone_outside_volume} )")
        orientation = (s.cone_x, s.cone_y, s.cone_z)
        if not labelled or any(c != UNSET for c in orientation):
            x, y, z = (_f(0.0 if c == UNSET else c) for c in orientation)
            out.append(f"call SetSoundConeOrientation( {v}, {x}, {y}, {z} )")
    return out


def init_sounds(world: World, previous: dict) -> str:
    lines = []
    for s in world.sounds.sounds:
        path, ms = previous.get(s.name, (None, None))
        if path != _q(s.path):
            data = world.audio(s.path)
            ms = (audio_ms(data) if data else None) or 0
        lines += ["    " + x for x in _sound_lines(s, world, ms)]
    return _function("InitSounds", lines)


def sections(world: World, script: str) -> dict:
    """Function texts (None when the map has no such elements) and global declarations, reusing sound durations and
    ambient sound heights already present in `script`."""
    paths = dict(_CREATE.findall(script))
    previous = {name: (paths.get(name), int(ms)) for name, ms in _DURATION.findall(script)}
    positions = {(snd, x, y): z for snd, x, y, z in _POSITION.findall(script)}
    return {"InitSounds": init_sounds(world, previous) if world.sounds and world.sounds.sounds else None,
            "CreateRegions": create_regions(world.regions, world.terrain, positions)
            if world.regions and world.regions.regions else None,
            "CreateCameras": create_cameras(world.cameras) if world.cameras and world.cameras.cameras else None,
            "globals": global_decls(world.regions, world.cameras, world.sounds)}
