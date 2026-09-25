"""Regions, cameras and sounds (war3map.w3r / w3c / w3s) as JSON lists with all-or-nothing upsert/delete edits.
Names are unique by script variable (gg_rct_ / gg_cam_ / gg_snd_); renames update GUI trigger references."""
import math
import posixpath
import re

from ..errors import ToolError
from ..formats import unitsdoo, w3c, w3r, w3s, wtg
from ..formats.binary import FormatError
from .gui import script_name
from .strings import load_strings
from .triggers import SCRIPT_WARNING, _all_params, _load, _read, _triggers, script_users

FILES = {"region": "war3map.w3r", "camera": "war3map.w3c", "sound": "war3map.w3s"}
SOUND_EXTENSIONS = (".flac", ".ogg", ".wav", ".mp3")
CODECS = {"region": (w3r, w3r.RegionFile, "regions"), "camera": (w3c, w3c.CameraFile, "cameras"),
          "sound": (w3s, w3s.SoundFile, "sounds")}
PREFIX = {"region": "gg_rct_", "camera": "gg_cam_", "sound": "gg_snd_"}
SOUND_FLAGS = {"looping": 1, "is_3d": 2, "stop_when_out_of_range": 4, "music": 8}
SOUND_INTS = ("fade_in", "fade_out", "volume", "priority", "channel", "cone_outside_volume")
SOUND_FLOATS = ("pitch", "pitch_variance", "min_distance", "max_distance", "distance_cutoff", "cone_inside",
                "cone_outside")
DIALOGUE_TEXT = ("speaker_unit", "facial_animation_label", "facial_animation_group_label", "facial_animation_set_path")
CAMERA_DEFAULTS = {"rotation": 90.0, "angle_of_attack": 304.0, "distance": 1650.0, "field_of_view": 70.0,
                   "far_z": 5000.0, "near_z": 100.0, "depth_of_field_scale": 0.01}  # everything else 0
REGION_COLOR = b"\xff\x80\x80\xff"
SOUND_NAME = re.compile(r"^gg_snd_[A-Za-z0-9_]+$")
ALLOWED = {
    "region": {"left", "bottom", "right", "top", "weather", "ambient_sound", "color"},
    "camera": {*w3c.FIELDS_V3, "camera_type"},
    "sound": {"path", "eax", "label", "dialogue", "cone_orientation", *SOUND_FLAGS, *SOUND_INTS, *SOUND_FLOATS},
}
_HINT = ('ops: {"op": "upsert", "name": "Spawn", "left": 0, "bottom": 0, "right": 512, "top": 512} creates or changes '
         '(add "new_name" to rename), {"op": "delete", "name": "Spawn"}; elements_list shows the fields')


# ---- values ----------------------------------------------------------------------------------------------------
def _kind(kind) -> None:
    if kind not in FILES:
        raise ToolError("bad_kind", f"unknown element kind {kind!r}", hint="one of: region, camera, sound")


def _bad(path: str, message: str) -> ToolError:
    return ToolError("bad_value", f"{path}: {message}", path=path)


def _int(v, path: str, lo: int = -2 ** 31, hi: int = 2 ** 31 - 1) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise _bad(path, f"expected an integer {lo}..{hi}")
    return v


def _num(v, path: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 3.4e38:
        raise _bad(path, "expected a number")
    return float(v)


def _bool(v, path: str) -> bool:
    if not isinstance(v, bool):
        raise _bad(path, "expected true or false")
    return v


def _text(v, path: str, allow_empty: bool = True) -> str:
    if not isinstance(v, str) or (not allow_empty and not v.strip()):
        raise _bad(path, "expected non-empty text" if not allow_empty else "expected text")
    return v


def _out(v: float) -> float:
    return float(f"{v:.7g}")  # the file stores 32-bit floats


def _opt_out(v: float) -> float | None:
    return None if v == w3s.UNSET else _out(v)


def _script(kind: str, name: str) -> str:
    return name if kind == "sound" else PREFIX[kind] + script_name(name)


# ---- files -----------------------------------------------------------------------------------------------------
def _load_file(project, kind: str):
    codec, cls, _ = CODECS[kind]
    data = _read(project, FILES[kind])
    if data is None:
        terrain = _read(project, "war3map.w3e") or b""
        newer = len(terrain) >= 8 and int.from_bytes(terrain[4:8], "little") >= 12
        return cls({"region": 7 if newer else 5, "camera": 3 if newer else 0, "sound": 3}[kind]), None
    try:
        return codec.parse(data), data
    except FormatError as e:
        raise ToolError("bad_file", f"{FILES[kind]}: {e}", hint="map_file_write can replace a damaged file") from e


def _region_json(g: w3r.Region) -> dict:
    return {"name": g.name, "script_name": _script("region", g.name), "index": g.index, "left": _out(g.left),
            "bottom": _out(g.bottom), "right": _out(g.right), "top": _out(g.top),
            "weather": None if g.weather == w3r.NO_ID else g.weather.decode("latin-1"),
            "ambient_sound": g.ambient_sound or None, "color": {"r": g.color[2], "g": g.color[1], "b": g.color[0]}}


def _camera_json(cam: w3c.Camera, version: int) -> dict:
    doc = {"name": cam.name, "script_name": _script("camera", cam.name)}
    doc.update({k: _out(v) for k, v in cam.values.items()})
    if version >= 3:
        doc["camera_type"] = cam.camera_type
    return doc


def _sound_json(s: w3s.Sound, strings) -> dict:
    doc = {"name": s.name, "path": s.path, "eax": s.eax}
    doc.update({k: bool(s.flags & bit) for k, bit in SOUND_FLAGS.items()})
    doc["unknown_flag_bits"] = s.flags & ~sum(SOUND_FLAGS.values())
    doc.update({k: getattr(s, k) for k in SOUND_INTS})
    doc.update({k: _opt_out(getattr(s, k)) for k in SOUND_FLOATS})
    doc["cone_orientation"] = [_opt_out(v) for v in (s.cone_x, s.cone_y, s.cone_z)]
    doc["label"] = s.label or None
    doc["dialogue"] = None
    if s.dialogue_text_key >= 0 or s.dialogue_speaker_key >= 0 or any(getattr(s, k) for k in DIALOGUE_TEXT):
        dialogue = {}
        for key, sid in (("text", s.dialogue_text_key), ("speaker", s.dialogue_speaker_key)):
            dialogue[key] = strings.get(sid) if sid >= 0 else None
            dialogue[key + "_ref"] = f"TRIGSTR_{sid}" if sid >= 0 else None
        dialogue.update({k: getattr(s, k) for k in DIALOGUE_TEXT})
        doc["dialogue"] = dialogue
    return doc


def elements_list(project, kind: str) -> dict:
    _kind(kind)
    model, _ = _load_file(project, kind)
    if kind == "region":
        items = [_region_json(g) for g in model.regions]
    elif kind == "camera":
        items = [_camera_json(c, model.version) for c in model.cameras]
    else:
        strings = load_strings(project)
        items = [_sound_json(s, strings) for s in model.sounds]
    return {"kind": kind, "file": FILES[kind], "version": model.version, "items": items}


# ---- edits -----------------------------------------------------------------------------------------------------
class _Edit:
    def __init__(self, project, catalog, kind: str):
        self.project, self.catalog, self.kind = project, catalog, kind
        self.model, self.before = _load_file(project, kind)
        self.items = getattr(self.model, CODECS[kind][2])
        self.strings = load_strings(project)
        self.wts_before = self.strings.serialize()
        try:
            self.tf, self.ct = _load(project, catalog.trigger_data)
            self.wtg_before = wtg.serialize(self.tf)
        except ToolError as e:
            if e.code != "no_triggers":
                raise
            self.tf = self.ct = self.wtg_before = None
        self.regions = None  # war3map.w3r loaded when a sound rename touches region ambient sounds
        self.created: list[str] = []
        self.warnings: list[str] = []
        self.skipped: list[str] = []   # deletes with missing_ok whose element was not there

    # names and references
    def _name(self, value, path: str) -> str:
        name = _text(value, path, allow_empty=False)
        if self.kind == "sound":
            name = name if name.startswith("gg_snd_") else "gg_snd_" + name
            if not SOUND_NAME.match(name):
                raise _bad(path, "sound names use letters, digits and _ (gg_snd_ is added when missing)")
        return name

    def _find(self, name: str):
        return next((x for x in self.items if x.name == name), None)

    def _check_free(self, name: str, skip, path: str) -> None:
        key = _script(self.kind, name)
        other = next((x for x in self.items if x is not skip and _script(self.kind, x.name) == key), None)
        if other is not None:
            raise ToolError("name_taken", f"{path}: {name!r} would share the script name {key} with {other.name!r}",
                            hint="choose a different name")

    def _texts(self):
        if self.tf is None:
            return []
        return [(t.name, text) for t, text in zip(_triggers(self.tf), self.ct.texts) if text] + [
            ("map header", self.ct.header or "")]

    def _users(self, script: str) -> list[str]:
        return script_users(self.tf, self.ct, script) if self.tf is not None else []

    def _sound_names(self) -> set[str]:
        sounds = self.items if self.kind == "sound" else _load_file(self.project, "sound")[0].sounds
        return {s.name for s in sounds}

    # field application
    def _catalog_id(self, kind: str, value, path: str) -> str:
        try:
            self.catalog.get(kind, value)
        except ToolError as e:
            if e.code != "not_found":
                raise
            raise ToolError("bad_value", f"{path}: no {kind} named {value!r}",
                            hint=f"data_search kind={kind} lists them", path=path) from e
        return value

    def _region(self, g: w3r.Region, fields: dict, path: str) -> None:
        for k in ("left", "bottom", "right", "top"):
            if k in fields:
                setattr(g, k, _num(fields[k], f"{path}.{k}"))
        if g.left > g.right or g.bottom > g.top:
            raise _bad(path, "left/bottom must not be greater than right/top")
        if "weather" in fields:
            v = fields["weather"]
            if v is None:
                g.weather = w3r.NO_ID
            elif isinstance(v, str) and len(v) == 4 and v.isascii():
                g.weather = self._catalog_id("weather", v, f"{path}.weather").encode("latin-1")
            else:
                raise _bad(f"{path}.weather", "expected a 4-character weather id such as 'RAlr', or null")
        if "ambient_sound" in fields:
            v = fields["ambient_sound"]
            if v not in (None, "") and (not isinstance(v, str) or v not in self._sound_names()):
                raise _bad(f"{path}.ambient_sound", f"no sound named {v!r} in the map (elements_list kind=sound)")
            g.ambient_sound = v or ""
        if "color" in fields:
            color, cpath = fields["color"], f"{path}.color"
            if not isinstance(color, dict) or set(color) != {"r", "g", "b"}:
                raise _bad(cpath, "expected {r, g, b}")
            r, gr, b = (_int(color[k], f"{cpath}.{k}", 0, 255) for k in "rgb")
            g.color = bytes([b, gr, r, g.color[3]])

    def _camera(self, cam: w3c.Camera, fields: dict, path: str) -> None:
        names = w3c.fields(self.model.version)
        for k, v in fields.items():
            if k == "camera_type" and self.model.version >= 3:
                cam.camera_type = _int(v, f"{path}.{k}")
            elif k not in names:
                raise _bad(f"{path}.{k}", f"this map's camera file (version {self.model.version}) has no {k}")
            else:
                cam.values[k] = _num(v, f"{path}.{k}")

    def _file_exists(self, value, path: str) -> str:
        value = _text(value, path, allow_empty=False)
        if value.replace("/", "\\").lower() in {f["name"].lower() for f in self.project.list_files()}:
            return value
        # the game plays any audio variant of a name (Reforged ships .ogg for scripts' .flac/.wav/.mp3 paths)
        stem = posixpath.splitext(value.replace("\\", "/"))[0]
        if any(self.catalog.storage.resolve(stem + ext, **self.catalog.layer) for ext in SOUND_EXTENSIONS):
            return value
        raise _bad(path, f"no sound file {value!r} in the map or the game data (data_search kind=file finds game "
                         "files; imports_edit adds your own)")

    def _sound(self, s: w3s.Sound, fields: dict, path: str) -> None:
        if "path" in fields:
            s.path = self._file_exists(fields["path"], f"{path}.path")
        if "eax" in fields:
            s.eax = _text(fields["eax"], f"{path}.eax", allow_empty=False)
        for k, bit in SOUND_FLAGS.items():
            if k in fields:
                s.flags = s.flags | bit if _bool(fields[k], f"{path}.{k}") else s.flags & ~bit
        for k in SOUND_INTS:
            if k in fields:
                setattr(s, k, _int(fields[k], f"{path}.{k}"))
        for k in SOUND_FLOATS:
            if k in fields:
                setattr(s, k, w3s.UNSET if fields[k] is None else _num(fields[k], f"{path}.{k}"))
        if "cone_orientation" in fields:
            v, cpath = fields["cone_orientation"], f"{path}.cone_orientation"
            if not isinstance(v, list) or len(v) != 3:
                raise _bad(cpath, "expected [x, y, z] with numbers or nulls")
            s.cone_x, s.cone_y, s.cone_z = (w3s.UNSET if x is None else _num(x, f"{cpath}[{i}]") for i, x in enumerate(v))
        if "label" in fields:
            v = fields["label"]
            s.label = "" if v in (None, "") else self._catalog_id("sound", _text(v, f"{path}.label"), f"{path}.label")
        if "dialogue" in fields:
            self._dialogue(s, fields["dialogue"], f"{path}.dialogue")

    def _dialogue(self, s: w3s.Sound, value, path: str) -> None:
        if value is None:
            s.dialogue_text_key = s.dialogue_speaker_key = -1
            for k in DIALOGUE_TEXT:
                setattr(s, k, "")
            return
        if not isinstance(value, dict) or set(value) - {"text", "speaker", *DIALOGUE_TEXT}:
            raise _bad(path, f"expected an object with text, speaker, {', '.join(DIALOGUE_TEXT)}")
        for key, attr in (("text", "dialogue_text_key"), ("speaker", "dialogue_speaker_key")):
            if key not in value:
                continue
            if value[key] is None:
                setattr(s, attr, -1)
                continue
            text, sid = _text(value[key], f"{path}.{key}"), getattr(s, attr)
            if sid >= 0:
                self.strings.set(sid, text)
            else:
                setattr(s, attr, self.strings.add(text))
        for k in DIALOGUE_TEXT:
            if k in value:
                setattr(s, k, _text(value[k], f"{path}.{k}"))

    # ops
    def op_upsert(self, op: dict, path: str) -> None:
        name = self._name(op.get("name"), f"{path}.name")
        fields = {k: v for k, v in op.items() if k not in ("op", "name", "new_name")}
        item = self._find(name)
        if item is None:
            self._check_free(name, None, f"{path}.name")
            required = {"region": ("left", "bottom", "right", "top"), "camera": ("x", "y"), "sound": ("path",)}
            missing = [k for k in required[self.kind] if k not in fields]
            if missing:
                raise _bad(path, f"a new {self.kind} needs {', '.join(missing)}")
            if self.kind == "region":
                item = w3r.Region(0.0, 0.0, 0.0, 0.0, name, max((g.index for g in self.items), default=-1) + 1,
                                  color=REGION_COLOR)
            elif self.kind == "camera":
                item = w3c.Camera(name, {f: CAMERA_DEFAULTS.get(f, 0.0) for f in w3c.fields(self.model.version)})
            else:
                item = w3s.Sound(name, "")
            self.items.append(item)
            self.created.append(name)
        getattr(self, "_" + self.kind)(item, fields, path)
        if "new_name" in op:
            self._rename(item, self._name(op["new_name"], f"{path}.new_name"), f"{path}.new_name")

    def _rename(self, item, new: str, path: str) -> None:
        if new == item.name:
            return
        self._check_free(new, item, path)
        old_script, new_script = _script(self.kind, item.name), _script(self.kind, new)
        if self.kind == "sound":
            if self.regions is None:
                self.regions = _load_file(self.project, "region")
            for g in self.regions[0].regions:
                if g.ambient_sound == item.name:
                    g.ambient_sound = new
        item.name = new
        if old_script == new_script or self.tf is None:
            return
        for t in _triggers(self.tf):
            for p in _all_params(t.ecas):
                if p.type == wtg.VARIABLE and p.value == old_script:
                    p.value = new_script
        mention = re.compile(rf"\b{re.escape(old_script)}\b")
        texts = [name for name, text in self._texts() if mention.search(text)]
        if texts:
            self.warnings.append(f"custom script in {', '.join(texts[:10])} still mentions {old_script}; update it")

    def op_delete(self, op: dict, path: str) -> None:
        name = self._name(op.get("name"), f"{path}.name")
        item = self._find(name)
        if item is None and op.get("missing_ok"):
            self.skipped.append(name)
            return
        if item is None:
            raise ToolError("not_found", f"{path}: no {self.kind} named {name!r}",
                            hint='elements_list lists them; "missing_ok": true skips a delete of one that is not there')
        script = _script(self.kind, item.name)
        users = self._users(script)
        if users:
            raise ToolError("in_use", f"{path}: {script} is used by {len(users)} trigger(s)",
                            hint="change or delete those triggers first", triggers=users[:20])
        if self.kind == "sound":
            regions = [g.name for g in _load_file(self.project, "region")[0].regions if g.ambient_sound == item.name]
            if regions:
                raise ToolError("in_use", f"{path}: {item.name} is the ambient sound of {len(regions)} region(s)",
                                hint="clear their ambient_sound first", regions=regions[:20])
        if self.kind == "region":
            self._check_waygates(item, path)
        self.items.remove(item)

    def _check_waygates(self, region: w3r.Region, path: str) -> None:
        data = _read(self.project, "war3mapUnits.doo")
        try:
            units = unitsdoo.parse(data).units if data else []
        except FormatError:
            units = []
        gates = [u.editor_id for u in units if u.waygate == region.index]
        if gates:
            raise ToolError("in_use", f"{path}: region {region.name!r} is the destination of {len(gates)} waygate(s)",
                            hint="change those waygates first (placed_edit)", units=gates[:20])

    def finish(self) -> dict:
        changed = False
        writes = [(self.kind, self.model, self.before)]
        if self.regions is not None:
            writes.append(("region", *self.regions))
        for kind, model, before in writes:
            if before is None and not getattr(model, CODECS[kind][2]):
                continue
            try:
                data = CODECS[kind][0].serialize(model)
            except FormatError as e:
                raise ToolError("bad_value", f"cannot encode {FILES[kind]}: {e}") from e
            if data != before:
                self.project.write(FILES[kind], data)
                changed = True
        if self.tf is not None:
            data = wtg.serialize(self.tf)
            if data != self.wtg_before:
                self.project.write("war3map.wtg", data)
        wts = self.strings.serialize()
        if wts != self.wts_before:
            self.project.write("war3map.wts", wts)
            changed = True
        if changed:
            self.warnings.append(SCRIPT_WARNING)
        return {"changed": changed, "created": self.created, "warnings": self.warnings,
                **({"skipped": self.skipped} if self.skipped else {})}


def elements_edit(project, catalog, kind: str, ops: list) -> dict:
    _kind(kind)
    edit = _Edit(project, catalog, kind)
    allowed = {"upsert": {"name", "new_name"} | ALLOWED[kind], "delete": {"name", "missing_ok"}}
    for i, op in enumerate(ops):
        path = f"ops[{i}]"
        try:
            action = op.get("op") if isinstance(op, dict) else None
            if action not in allowed:
                raise ToolError("bad_op", f"{path}: unknown op {action!r}", hint=_HINT)
            extra = set(op) - {"op"} - allowed[action]
            if extra:
                raise ToolError("bad_op", f"{path}: unknown keys {sorted(extra)} for {kind} {action}", hint=_HINT)
            getattr(edit, f"op_{action}")(op, path)
        except ToolError as e:
            e.details.setdefault("op_index", i)
            if e.code == "bad_value" and not e.hint:
                e.hint = "elements_list shows the fields"
            raise
    return edit.finish()
