"""MDL models: the text form of the models in formats/mdx.py (same dict shape, so mdx.serialize(mdl.parse(text)) works).

The syntax is the common MDL dialect (Blizzard's exporters, mdx-m3-viewer, Retera's Model Studio): blocks, "static"
values, animation tracks with DontInterp / Linear / Hermite / Bezier keys, colours written RGB. Floats are written as
the shortest text that reads back to the same 32-bit value. Every object block is read back as it is written; whatever
the dialect cannot hold (unknown flag bits, names with bytes after their terminator, unknown chunks, fields without an
MDL keyword) is added as "//@ key json" lines, which other MDL readers skip as comments. So parse(serialize(model))
equals the model and MDX -> MDL -> MDX is byte-exact.

Reforged layers (version 1100+) write each layer texture as "Texture { static TextureID n, Semantic n, [TextureID
track] }" and the layer's HD value as "HD n"; the dialect has no agreed form for them."""
import json
import re
import struct

from . import mdx
from .binary import FormatError

NO_ID = mdx.NO_ID
_F32 = struct.Struct("<f")
_ZERO = b"\0\0\0\0"


# ---- text output -----------------------------------------------------------------------------------------------
def _f(v: float) -> str:
    """shortest text that reads back as the same float32"""
    packed = _F32.pack(v)
    for digits in (6, 7, 8):
        s = f"{v:.{digits}g}"
        try:
            if _F32.pack(float(s)) == packed:
                return s
        except OverflowError:
            break
    return f"{v:.9g}"


def _num(v) -> str:
    return _f(v) if isinstance(v, float) else str(v)


def _nums(values) -> str:
    return ", ".join(map(_num, values))


def _vec(values) -> str:
    return "{ " + _nums(values) + " }"


def _rgb(bgr) -> str:
    return _vec(bgr[::-1])


def _id(v: int) -> int:
    return -1 if v == NO_ID else v


def _q(value) -> str:
    if isinstance(value, bytes):
        value = value.split(b"\0")[0].decode("utf-8", "surrogateescape")
    if re.search(r'[\r\n]|\\"|\\$', value):
        value = re.sub(r'[\r\n"]', "'", value).rstrip("\\")   # not writable: the read-back check adds the exact value
    return '"' + value.replace('"', '\\"') + '"'


def _is(v: float, default: float) -> bool:
    return _F32.pack(v) == _F32.pack(default)


def _zero(values) -> bool:
    return all(_F32.pack(v) == _ZERO for v in values)


def _blk(header: str, lines: list[str]) -> list[str]:
    return [header + " {"] + ["\t" + line for line in lines] + ["}"]


def _flag_lines(value: int, names) -> list[str]:
    return [f"{word}," for word, bit in names if value & bit]


def _json(value) -> str:
    return json.dumps(value, default=lambda b: {"hex": b.hex()}, separators=(",", ":"))


def _unjson(text: str):
    try:
        return json.loads(text, object_hook=lambda d: bytes.fromhex(d["hex"]) if d.keys() == {"hex"} else d)
    except ValueError as e:
        raise FormatError(f"MDL extension value is not JSON: {text[:60]!r}") from e


# ---- text input ------------------------------------------------------------------------------------------------
# a brace group of plain numbers is one token (one statement holding the numbers): most of a model's text
_TOKEN = re.compile(r'\{([-+.\deE\s,]*)\}|//@[ \t]*([\w.]+)[ \t]+([^\r\n]*)|//[^\n]*|"((?:[^"\\\r\n]|\\.)*)"|([{},])'
                    r'|([^\s,:{}"/]+)|[\s:]+|(.)')
_EXT = "//@"


class _Q(str):
    """a quoted string token"""


def _tree(text: str) -> list:
    """statements: (atoms, block or None); extension lines are ((_EXT, key), value)"""
    root: list = []
    stack, atoms = [root], []
    for m in _TOKEN.finditer(text):
        numbers, key, js, s, p, w, bad = m.groups()
        if w is not None:
            atoms.append(w)
        elif numbers is not None:
            values = numbers.replace(",", " ").split()
            stack[-1].append((atoms, [(values, None)] if values else []))
            atoms = []
        elif s is not None:
            atoms.append(_Q(s.replace('\\"', '"')))
        elif p == "{":
            block: list = []
            stack[-1].append((atoms, block))
            stack.append(block)
            atoms = []
        elif p is not None:
            if atoms:
                stack[-1].append((atoms, None))
                atoms = []
            if p == "}":
                if len(stack) == 1:
                    raise FormatError(f"MDL has an unmatched '}}' at offset {m.start()}")
                stack.pop()
        elif key is not None:
            if atoms:
                stack[-1].append((atoms, None))
                atoms = []
            stack[-1].append(((_EXT, key), _unjson(js)))
        elif bad is not None:
            raise FormatError(f"MDL has an unexpected {bad!r} at offset {m.start()}")
    if len(stack) != 1 or atoms:
        raise FormatError("MDL text ends inside a block or statement")
    return root


def _flat(block) -> list:
    out = []
    for atoms, sub in block or ():
        if type(atoms) is tuple:
            continue
        out.extend(atoms)
        if sub is not None:
            out.extend(_flat(sub))
    return out


def _int(t: str) -> int:
    try:
        return int(t)
    except ValueError:
        try:
            return int(float(t))
        except ValueError:
            raise FormatError(f"MDL expected a number, found {t!r}") from None


def _u32(t: str) -> int:
    return _int(t) & 0xFFFFFFFF


def _i32(t: str) -> int:
    v = _int(t) & 0xFFFFFFFF
    return v - (1 << 32) if v >= 1 << 31 else v


def _float(t: str) -> float:
    try:
        return float(t)
    except ValueError:
        raise FormatError(f"MDL expected a number, found {t!r}") from None


class _Block:
    def __init__(self, stmts, what: str):
        self.what, self.items, self.ext, self.used = what, [], [], set()
        for atoms, block in stmts:
            if type(atoms) is tuple:
                self.ext.append((atoms[1], block))
            elif not atoms:
                raise FormatError(f"MDL block without a keyword in {what}")
            elif atoms[0] == "static" and len(atoms) > 1:
                self.items.append(("static " + atoms[1], atoms[2:], block))
            else:
                self.items.append((atoms[0], atoms[1:], block))

    def all(self, key: str) -> list:
        self.used.add(key)
        return [(rest, block) for k, rest, block in self.items if k == key]

    def has(self, key: str) -> bool:
        return bool(self.all(key))

    def value(self, key: str, conv, default):
        found = self.all(key)
        if not found:
            return default
        rest, block = found[0]
        if block is not None:
            return [conv(t) for t in _flat(block)]
        if not rest:
            raise FormatError(f"MDL {key} in {self.what} has no value")
        return conv(rest[0])

    def flags(self, names, value: int = 0) -> int:
        for word, bit in names:
            if self.has(word):
                value |= bit
        return value

    def choice(self, words, default: int = 0) -> int:
        return next((i for i, w in enumerate(words) if self.has(w)), default)

    def tracks(self, words: dict) -> list:
        out = []
        for k, rest, block in self.items:
            tag = words.get(k) or (k if k in mdx.TRACKS else None)
            if tag and block is not None and len(rest) == 1:
                self.used.add(k)
                out.append(_read_track(tag, block, f"{k} in {self.what}"))
        return out

    def finish(self, obj: dict) -> dict:
        unknown = [k for k, _, _ in self.items if k not in self.used and not k.startswith("Num")]
        if unknown:
            raise FormatError(f"unknown MDL token {unknown[0]!r} in {self.what}")
        for key, value in self.ext:
            *path, last = key.split(".")
            target = obj
            for p in path:
                target = target[p]
            target[last] = value
        return obj


def _name(atoms) -> str:
    return str(atoms[1]) if len(atoms) > 1 else ""


# ---- read-back check -------------------------------------------------------------------------------------------
def _same(a, b) -> bool:
    if type(a) is not type(b):
        return False
    if type(a) is float:
        try:
            return _F32.pack(a) == _F32.pack(b)
        except OverflowError:
            return False
    if type(a) is list:
        if len(a) != len(b):
            return False
        if a and type(a[0]) is float and type(b[0]) is float:   # number lists: compare as stored bytes
            try:
                return struct.pack(f"<{len(a)}f", *a) == struct.pack(f"<{len(b)}f", *b)
            except (struct.error, TypeError, OverflowError):
                return False
        if a and type(a[0]) is int and type(a[-1]) is int:   # index lists (track keys start with an int, too)
            return a == b
        return all(map(_same, a, b))
    if type(a) is dict:
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    return a == b


def _diff(obj: dict, back: dict, prefix: str = ""):
    for key, value in obj.items():
        if key in back and _same(value, back[key]):
            continue
        if isinstance(value, dict) and isinstance(back.get(key), dict):
            yield from _diff(value, back[key], f"{prefix}{key}.")
        else:
            yield prefix + key, value
    for key in back:
        if key not in obj:
            raise FormatError(f"MDL reader made an extra field {prefix}{key}")


def _emit(header: str, lines: list[str], obj: dict, read, version: int) -> list[str]:
    block = _blk(header, lines)
    (atoms, body), = _tree("\n".join(block))
    extra = [f"//@ {key} {_json(value)}" for key, value in _diff(obj, read(atoms, body, version))]
    return _blk(header, lines + extra) if extra else block


# ---- tracks ----------------------------------------------------------------------------------------------------
_INTERPOLATION = ("DontInterp", "Linear", "Hermite", "Bezier")


def _track_lines(word: str, t: dict) -> list[str]:
    single = mdx.TRACKS[t["tag"]] in ("u", 1)
    value = (lambda v: _num(v[0])) if single else _vec
    lines = [_INTERPOLATION[t["interpolation"]] + ","] if t["interpolation"] < 4 else []
    if t["global_sequence"] != -1:
        lines.append(f"GlobalSeqId {t['global_sequence']},")
    for key in t["keys"]:
        lines.append(f"{key[0]}: {value(key[1])},")
        if len(key) > 2:
            lines += [f"\tInTan {value(key[2])},", f"\tOutTan {value(key[3])},"]
    return _blk(f"{word} {len(t['keys'])}", lines)


def _tracks_lines(tracks: list, names: dict) -> list[str]:
    return [line for t in tracks for line in _track_lines(names.get(t["tag"], t["tag"]), t)]


def _read_track(tag: str, block, what: str) -> dict:
    conv = _u32 if mdx.TRACKS[tag] == "u" else _float
    t = {"tag": tag, "interpolation": 0, "global_sequence": -1, "keys": []}
    keys = t["keys"]
    for atoms, sub in block:
        if type(atoms) is tuple or not atoms:
            raise FormatError(f"MDL track {what} has an unexpected block")
        word = atoms[0]
        value = [conv(v) for v in _flat(sub)] if sub is not None else [conv(v) for v in atoms[1:2]]
        if word in _INTERPOLATION and sub is None and len(atoms) == 1:
            t["interpolation"] = _INTERPOLATION.index(word)
        elif word == "GlobalSeqId":
            t["global_sequence"] = _i32(atoms[1])
        elif word in ("InTan", "OutTan"):
            if not keys or len(keys[-1]) != (2 if word == "InTan" else 3):
                raise FormatError(f"MDL track {what} has a misplaced {word}")
            keys[-1].append(value)
        else:
            keys.append([_i32(word), value])
    if any(len(k) != (4 if t["interpolation"] > 1 else 2) for k in keys):
        raise FormatError(f"MDL track {what} needs InTan and OutTan exactly when it is Hermite or Bezier")
    return t


def _words(names: dict) -> dict:
    return {word: tag for tag, word in names.items()}


# ---- shared parts ----------------------------------------------------------------------------------------------
def _extent_lines(e: dict) -> list[str]:
    lines = []
    if not _zero(e["minimum"]):
        lines.append(f"MinimumExtent {_vec(e['minimum'])},")
    if not _zero(e["maximum"]):
        lines.append(f"MaximumExtent {_vec(e['maximum'])},")
    if not _zero([e["bounds_radius"]]):
        lines.append(f"BoundsRadius {_f(e['bounds_radius'])},")
    return lines


def _read_extent(b: _Block) -> dict:
    return {"bounds_radius": b.value("BoundsRadius", _float, 0.0), "minimum": b.value("MinimumExtent", _float, [0.0] * 3),
            "maximum": b.value("MaximumExtent", _float, [0.0] * 3)}


_BILLBOARD = (("BillboardedLockZ", 0x40), ("BillboardedLockY", 0x20), ("BillboardedLockX", 0x10), ("Billboarded", 0x8),
              ("CameraAnchored", 0x80))
_INHERIT = (("Translation", 0x1), ("Scaling", 0x2), ("Rotation", 0x4))
_NODE_TRACKS = {"KGTR": "Translation", "KGRT": "Rotation", "KGSC": "Scaling"}


def _node_lines(node: dict, extra_flags=()) -> list[str]:
    lines = [f"ObjectId {_id(node['object_id'])},"]
    if node["parent_id"] != NO_ID:
        lines.append(f"Parent {node['parent_id']},")
    lines += _flag_lines(node["flags"], _BILLBOARD + extra_flags)
    lines += [f"DontInherit {{ {word} }}," for word, bit in _INHERIT if node["flags"] & bit]
    return lines


def _read_node(atoms, b: _Block, type_bit: int, extra_flags=()) -> dict:
    flags = b.flags(_BILLBOARD + extra_flags, type_bit)
    for _, block in b.all("DontInherit"):
        words = _flat(block)
        flags |= sum(bit for word, bit in _INHERIT if word in words)
    return {"name": _name(atoms), "object_id": b.value("ObjectId", _u32, NO_ID), "parent_id": b.value("Parent", _u32, NO_ID),
            "flags": flags, "tracks": []}


def _node_object(atoms, b: _Block, type_bit: int, names: dict, extra_flags=()) -> tuple[dict, dict]:
    """(object with its node, object tracks) for the nested node kinds"""
    node = _read_node(atoms, b, type_bit, extra_flags)
    tracks = b.tracks({**_words(_NODE_TRACKS), **_words(names)})
    node["tracks"] = [t for t in tracks if t["tag"] in _NODE_TRACKS]
    return {"node": node, "tracks": [t for t in tracks if t["tag"] not in _NODE_TRACKS]}


def _node_object_lines(obj: dict, names: dict, fields: list[str], extra_flags=()) -> list[str]:
    return (_node_lines(obj["node"], extra_flags) + fields + _tracks_lines(obj["node"]["tracks"], _NODE_TRACKS)
            + _tracks_lines(obj["tracks"], names))


def _string(b: _Block, key: str) -> str:
    return b.value(key, str, "")


# ---- model, sequences, textures --------------------------------------------------------------------------------
def _w_model(info: dict, v: int) -> list[str]:
    lines = [f"BlendTime {info['blend_time']},"] + _extent_lines(info)
    if info["animation_file"]:
        lines.append(f"AnimationFile {_q(info['animation_file'])},")
    return _emit(f"Model {_q(info['name'])}", lines, info, _r_model, v)


def _r_model(atoms, body, v: int) -> dict:
    b = _Block(body, "Model")
    return b.finish({"name": _name(atoms), "animation_file": _string(b, "AnimationFile"), **_read_extent(b),
                     "blend_time": b.value("BlendTime", _u32, 150)})


def _w_sequence(s: dict, v: int) -> list[str]:
    lines = [f"Interval {_vec(s['interval'])},"] + (["NonLooping,"] if s["flags"] & 1 else [])
    if not _zero([s["move_speed"]]):
        lines.append(f"MoveSpeed {_f(s['move_speed'])},")
    if not _zero([s["rarity"]]):
        lines.append(f"Rarity {_f(s['rarity'])},")
    return _emit(f"Anim {_q(s['name'])}", lines + _extent_lines(s), s, _r_sequence, v)


def _r_sequence(atoms, body, v: int) -> dict:
    b = _Block(body, "Anim")
    return b.finish({"name": _name(atoms), "interval": b.value("Interval", _u32, [0, 0]),
                     "move_speed": b.value("MoveSpeed", _float, 0.0), "flags": b.flags((("NonLooping", 1),)),
                     "rarity": b.value("Rarity", _float, 0.0), "sync_point": 0, **_read_extent(b)})


_WRAP = (("WrapWidth", 1), ("WrapHeight", 2))


def _w_texture(t: dict, v: int) -> list[str]:
    lines = [f"Image {_q(t['path'])},"]
    if t["replaceable_id"]:
        lines.append(f"ReplaceableId {t['replaceable_id']},")
    return _emit("Bitmap", lines + _flag_lines(t["flags"], _WRAP), t, _r_texture, v)


def _r_texture(atoms, body, v: int) -> dict:
    b = _Block(body, "Bitmap")
    return b.finish({"replaceable_id": b.value("ReplaceableId", _u32, 0), "path": _string(b, "Image"),
                     "flags": b.flags(_WRAP)})


# ---- materials -------------------------------------------------------------------------------------------------
_MATERIAL_FLAGS = (("ConstantColor", 0x1), ("TwoSided", 0x2), ("SortPrimsNearZ", 0x8), ("SortPrimsFarZ", 0x10),
                   ("FullResolution", 0x20))
_FILTERS = ("None", "Transparent", "Blend", "Additive", "AddAlpha", "Modulate", "Modulate2x")
_LAYER_FLAGS = (("Unshaded", 0x1), ("SphereEnvMap", 0x2), ("TwoSided", 0x10), ("Unfogged", 0x20), ("NoDepthTest", 0x40),
                ("NoDepthSet", 0x80), ("Unlit", 0x100))
_LAYER_TRACKS = {"KMTF": "TextureID", "KMTA": "Alpha", "KMTE": "EmissiveGain", "KFC3": "FresnelColor",
                 "KFCA": "FresnelOpacity", "KFTC": "FresnelTeamColor"}


def _w_material(m: dict, v: int) -> list[str]:
    lines = _flag_lines(m["flags"], _MATERIAL_FLAGS)
    if m["priority_plane"]:
        lines.append(f"PriorityPlane {m['priority_plane']},")
    if "shader" in m:
        lines.append(f"Shader {_q(m['shader'])},")
    for layer in m["layers"]:
        lines += _w_layer(layer, v)
    return _emit("Material", lines, m, _r_material, v)


def _r_material(atoms, body, v: int) -> dict:
    b = _Block(body, "Material")
    m = {"priority_plane": b.value("PriorityPlane", _i32, 0), "flags": b.flags(_MATERIAL_FLAGS)}
    if 800 < v < 1100:
        m["shader"] = _string(b, "Shader")
    m["layers"] = [_r_layer(["Layer"], block, v) for _, block in b.all("Layer")]
    return b.finish(m)


def _w_layer(layer: dict, v: int) -> list[str]:
    fm = layer["filter_mode"]
    lines = [f"FilterMode {_FILTERS[fm] if fm < len(_FILTERS) else 'None'},"]
    lines += _flag_lines(layer["flags"], _LAYER_FLAGS)
    lines.append(f"static TextureID {_id(layer['texture_id'])},")
    if layer["texture_animation_id"] != NO_ID:
        lines.append(f"TVertexAnimId {layer['texture_animation_id']},")
    if layer["coord_id"]:
        lines.append(f"CoordId {layer['coord_id']},")
    if not _is(layer["alpha"], 1.0):
        lines.append(f"static Alpha {_f(layer['alpha'])},")
    if "emissive_gain" in layer and not _is(layer["emissive_gain"], 1.0):
        lines.append(f"static EmissiveGain {_f(layer['emissive_gain'])},")
    if "fresnel_color" in layer:
        if not all(_is(c, 1.0) for c in layer["fresnel_color"]):
            lines.append(f"static FresnelColor {_vec(layer['fresnel_color'])},")
        if not _zero([layer["fresnel_opacity"]]):
            lines.append(f"static FresnelOpacity {_f(layer['fresnel_opacity'])},")
        if not _zero([layer["fresnel_team_color"]]):
            lines.append(f"static FresnelTeamColor {_f(layer['fresnel_team_color'])},")
    if "hd" in layer:
        lines.append(f"HD {layer['hd']},")
        for texture in layer["textures"]:
            lines += _blk("Texture", [f"static TextureID {_id(texture['texture_id'])},", f"Semantic {texture['semantic']},"]
                          + _tracks_lines(texture["tracks"], _LAYER_TRACKS))
    lines += _tracks_lines(layer["tracks"], _LAYER_TRACKS)
    return _emit("Layer", lines, layer, _r_layer, v)


def _r_layer(atoms, body, v: int) -> dict:
    b = _Block(body, "Layer")
    mode = b.value("FilterMode", str, "None")
    if mode not in _FILTERS:
        raise FormatError(f"unknown MDL filter mode {mode!r}")
    layer = {"filter_mode": _FILTERS.index(mode), "flags": b.flags(_LAYER_FLAGS),
             "texture_id": b.value("static TextureID", _u32, 0), "texture_animation_id": b.value("TVertexAnimId", _u32, NO_ID),
             "coord_id": b.value("CoordId", _u32, 0), "alpha": b.value("static Alpha", _float, 1.0)}
    if v > 800:
        layer["emissive_gain"] = b.value("static EmissiveGain", _float, 1.0)
    if v > 900:
        layer.update({"fresnel_color": b.value("static FresnelColor", _float, [1.0] * 3),
                      "fresnel_opacity": b.value("static FresnelOpacity", _float, 0.0),
                      "fresnel_team_color": b.value("static FresnelTeamColor", _float, 0.0)})
    if v > 1000:
        layer["hd"] = b.value("HD", _u32, 0)
        layer["textures"] = []
        for _, block in b.all("Texture"):
            t = _Block(block, "Texture")
            layer["textures"].append(t.finish({"texture_id": t.value("static TextureID", _u32, 0),
                                               "semantic": t.value("Semantic", _u32, 0),
                                               "tracks": t.tracks(_words(_LAYER_TRACKS))}))
    layer["tracks"] = b.tracks(_words(_LAYER_TRACKS))
    return b.finish(layer)


_TEXTURE_ANIMATION_TRACKS = {"KTAT": "Translation", "KTAR": "Rotation", "KTAS": "Scaling"}


def _w_texture_animation(a: dict, v: int) -> list[str]:
    return _emit("TVertexAnim", _tracks_lines(a["tracks"], _TEXTURE_ANIMATION_TRACKS), a, _r_texture_animation, v)


def _r_texture_animation(atoms, body, v: int) -> dict:
    b = _Block(body, "TVertexAnim")
    return b.finish({"tracks": b.tracks(_words(_TEXTURE_ANIMATION_TRACKS))})


# ---- geosets ---------------------------------------------------------------------------------------------------
_FACE_TYPES = ("Points", "Lines", "LineLoop", "LineStrip", "Triangles", "TriangleStrip", "TriangleFan", "Quads",
               "QuadStrip", "Polygons")


def _rows(word: str, values: list, n: int) -> list[str]:
    return _blk(f"{word} {len(values) // n}", ["{ " + _nums(values[i:i + n]) + " }," for i in range(0, len(values), n)])


def _w_geoset(g: dict, v: int) -> list[str]:
    lines = _rows("Vertices", g["vertices"], 3) + _rows("Normals", g["normals"], 3)
    for uv in g["uvs"]:
        lines += _rows("TVertices", uv, 2)
    lines += _blk("VertexGroup", [f"{x}," for x in g["vertex_groups"]])
    if "tangents" in g:
        lines += _rows("Tangents", g["tangents"], 4)
    if "skin" in g:
        lines += _blk(f"SkinWeights {len(g['skin']) // 8}",
                      [_nums(g["skin"][i:i + 8]) + "," for i in range(0, len(g["skin"]), 8)])
    faces, pos = [], 0
    for kind, count in zip(g["face_types"], g["face_groups"]):
        faces += _blk(_FACE_TYPES[kind] if kind < len(_FACE_TYPES) else "Triangles",
                      ["{ " + _nums(g["faces"][pos:pos + count]) + " },"])
        pos += count
    lines += _blk(f"Faces {len(g['face_groups'])} {len(g['faces'])}", faces)
    groups, pos = [], 0
    for size in g["matrix_groups"]:
        groups.append(f"Matrices {_vec(g['matrix_indices'][pos:pos + size])},")
        pos += size
    lines += _blk(f"Groups {len(g['matrix_groups'])} {len(g['matrix_indices'])}", groups)
    lines += _extent_lines(g["extent"])
    for e in g["sequence_extents"]:
        lines += _blk("Anim", _extent_lines(e))
    lines += [f"MaterialID {g['material_id']},", f"SelectionGroup {g['selection_group']},"]
    if g["selection_flags"] == 4:
        lines.append("Unselectable,")
    if "lod" in g:
        lines.append(f"LevelOfDetail {g['lod']},")
        if g["lod_name"]:
            lines.append(f"Name {_q(g['lod_name'])},")
    return _emit("Geoset", lines, g, _r_geoset, v)


def _r_geoset(atoms, body, v: int) -> dict:
    b = _Block(body, "Geoset")

    def flat(key, conv):
        return [conv(t) for _, block in b.all(key)[:1] for t in _flat(block)]

    g = {"vertices": flat("Vertices", _float), "normals": flat("Normals", _float), "face_types": [], "face_groups": [],
         "faces": [], "vertex_groups": flat("VertexGroup", _u32), "matrix_groups": [], "matrix_indices": []}
    for _, block in b.all("Faces"):
        for kind, sub in block:
            if type(kind) is tuple or not kind or kind[0] not in _FACE_TYPES:
                raise FormatError(f"unknown MDL face type {kind!r}")
            indices = [_u32(t) for t in _flat(sub)]
            g["face_types"].append(_FACE_TYPES.index(kind[0]))
            g["face_groups"].append(len(indices))
            g["faces"] += indices
    for _, block in b.all("Groups"):
        for atoms_, sub in block:
            if type(atoms_) is tuple or atoms_ != ["Matrices"]:
                raise FormatError("MDL Groups holds only Matrices")
            indices = [_u32(t) for t in _flat(sub)]
            g["matrix_groups"].append(len(indices))
            g["matrix_indices"] += indices
    g.update({"material_id": b.value("MaterialID", _u32, 0), "selection_group": b.value("SelectionGroup", _u32, 0),
              "selection_flags": 4 if b.has("Unselectable") else 0})
    if v > 800:
        g["lod"], g["lod_name"] = b.value("LevelOfDetail", _u32, 0), _string(b, "Name")
    g["extent"] = _read_extent(b)
    g["sequence_extents"] = []
    for _, block in b.all("Anim"):
        e = _Block(block, "Geoset Anim")
        g["sequence_extents"].append(e.finish(_read_extent(e)))
    if v > 800:
        if b.has("Tangents"):
            g["tangents"] = flat("Tangents", _float)
        if b.has("SkinWeights"):
            g["skin"] = flat("SkinWeights", _u32)
    g["uvs"] = [[_float(t) for t in _flat(block)] for _, block in b.all("TVertices")]
    return b.finish(g)


_GEOSET_ANIMATION_TRACKS = {"KGAO": "Alpha", "KGAC": "Color"}


def _w_geoset_animation(a: dict, v: int) -> list[str]:
    lines = (["DropShadow,"] if a["flags"] & 1 else []) + [f"static Alpha {_f(a['alpha'])},"]
    if a["flags"] & 2:
        lines.append(f"static Color {_rgb(a['color'])},")
    lines += [f"GeosetId {_id(a['geoset_id'])},"] + _tracks_lines(a["tracks"], _GEOSET_ANIMATION_TRACKS)
    return _emit("GeosetAnim", lines, a, _r_geoset_animation, v)


def _r_geoset_animation(atoms, body, v: int) -> dict:
    b = _Block(body, "GeosetAnim")
    a = {"alpha": b.value("static Alpha", _float, 1.0), "color": b.value("static Color", _float, [1.0] * 3)[::-1],
         "geoset_id": b.value("GeosetId", _u32, NO_ID), "tracks": b.tracks(_words(_GEOSET_ANIMATION_TRACKS))}
    colored = b.has("static Color") or any(t["tag"] == "KGAC" for t in a["tracks"])
    a["flags"] = b.flags((("DropShadow", 1),)) | (2 if colored else 0)
    return b.finish(a)


# ---- nodes -----------------------------------------------------------------------------------------------------
def _w_bone(bone: dict, v: int) -> list[str]:
    lines = _node_lines(bone) + [
        f"GeosetId {'Multiple' if bone['geoset_id'] == NO_ID else bone['geoset_id']},",
        f"GeosetAnimId {'None' if bone['geoset_animation_id'] == NO_ID else bone['geoset_animation_id']},"]
    return _emit(f"Bone {_q(bone['name'])}", lines + _tracks_lines(bone["tracks"], _NODE_TRACKS), bone, _r_bone, v)


def _r_bone(atoms, body, v: int) -> dict:
    b = _Block(body, "Bone")
    bone = _read_node(atoms, b, 0x100)
    bone["tracks"] = b.tracks(_words(_NODE_TRACKS))
    bone["geoset_id"] = b.value("GeosetId", lambda t: NO_ID if t == "Multiple" else _u32(t), NO_ID)
    bone["geoset_animation_id"] = b.value("GeosetAnimId", lambda t: NO_ID if t == "None" else _u32(t), NO_ID)
    return b.finish(bone)


def _w_helper(helper: dict, v: int) -> list[str]:
    return _emit(f"Helper {_q(helper['name'])}", _node_lines(helper) + _tracks_lines(helper["tracks"], _NODE_TRACKS),
                 helper, _r_helper, v)


def _r_helper(atoms, body, v: int) -> dict:
    b = _Block(body, "Helper")
    helper = _read_node(atoms, b, 0)
    helper["tracks"] = b.tracks(_words(_NODE_TRACKS))
    return b.finish(helper)


_LIGHT_TYPES = ("Omnidirectional", "Directional", "Ambient")
_LIGHT_TRACKS = {"KLAS": "AttenuationStart", "KLAE": "AttenuationEnd", "KLAC": "Color", "KLAI": "Intensity",
                 "KLBI": "AmbIntensity", "KLBC": "AmbColor", "KLAV": "Visibility"}


def _w_light(light: dict, v: int) -> list[str]:
    fields = [f"{_LIGHT_TYPES[light['type']]}," if light["type"] < 3 else "Omnidirectional,",
              f"static AttenuationStart {_f(light['attenuation'][0])},", f"static AttenuationEnd {_f(light['attenuation'][1])},",
              f"static Intensity {_f(light['intensity'])},", f"static Color {_rgb(light['color'])},",
              f"static AmbIntensity {_f(light['ambient_intensity'])},", f"static AmbColor {_rgb(light['ambient_color'])},"]
    return _emit(f"Light {_q(light['node']['name'])}", _node_object_lines(light, _LIGHT_TRACKS, fields), light, _r_light, v)


def _r_light(atoms, body, v: int) -> dict:
    b = _Block(body, "Light")
    light = _node_object(atoms, b, 0x200, _LIGHT_TRACKS)
    light.update({"type": b.choice(_LIGHT_TYPES), "attenuation": [b.value("static AttenuationStart", _float, 0.0),
                                                                   b.value("static AttenuationEnd", _float, 0.0)],
                  "color": b.value("static Color", _float, [1.0] * 3)[::-1], "intensity": b.value("static Intensity", _float, 0.0),
                  "ambient_color": b.value("static AmbColor", _float, [1.0] * 3)[::-1],
                  "ambient_intensity": b.value("static AmbIntensity", _float, 0.0)})
    if v >= 1600:
        light.update({"unknown_1": 0, "unknown_2": [0.0] * 6})
    return b.finish(light)


_ATTACHMENT_TRACKS = {"KATV": "Visibility"}


def _w_attachment(a: dict, v: int) -> list[str]:
    fields = [f"AttachmentID {a['attachment_id']},"] + ([f"Path {_q(a['path'])},"] if a["path"] else [])
    return _emit(f"Attachment {_q(a['node']['name'])}", _node_object_lines(a, _ATTACHMENT_TRACKS, fields), a,
                 _r_attachment, v)


def _r_attachment(atoms, body, v: int) -> dict:
    b = _Block(body, "Attachment")
    a = _node_object(atoms, b, 0x800, _ATTACHMENT_TRACKS)
    a.update({"path": _string(b, "Path"), "attachment_id": b.value("AttachmentID", _u32, 0)})
    return b.finish(a)


_EMITTER_FLAGS = (("EmitterUsesMDL", 0x8000), ("EmitterUsesTGA", 0x10000))
_EMITTER_TRACKS = {"KPEE": "EmissionRate", "KPEG": "Gravity", "KPLN": "Longitude", "KPLT": "Latitude",
                   "KPEV": "Visibility", "KPEL": "LifeSpan", "KPES": "InitVelocity"}


def _w_emitter(e: dict, v: int) -> list[str]:
    fields = [f"static EmissionRate {_f(e['emission_rate'])},", f"static Gravity {_f(e['gravity'])},",
              f"static Longitude {_f(e['longitude'])},", f"static Latitude {_f(e['latitude'])},"]
    fields += _blk("Particle", [f"static LifeSpan {_f(e['lifespan'])},", f"static InitVelocity {_f(e['speed'])},",
                                f"Path {_q(e['path'])},"])
    return _emit(f"ParticleEmitter {_q(e['node']['name'])}", _node_object_lines(e, _EMITTER_TRACKS, fields, _EMITTER_FLAGS),
                 e, _r_emitter, v)


def _r_emitter(atoms, body, v: int) -> dict:
    b = _Block(body, "ParticleEmitter")
    e = _node_object(atoms, b, 0x1000, _EMITTER_TRACKS, _EMITTER_FLAGS)
    p = _Block(next((block for _, block in b.all("Particle")), []), "Particle")
    e["tracks"] += p.tracks(_words(_EMITTER_TRACKS))
    e.update({"emission_rate": b.value("static EmissionRate", _float, 0.0), "gravity": b.value("static Gravity", _float, 0.0),
              "longitude": b.value("static Longitude", _float, 0.0), "latitude": b.value("static Latitude", _float, 0.0),
              "path": _string(p, "Path"), "lifespan": p.value("static LifeSpan", _float, 0.0),
              "speed": p.value("static InitVelocity", _float, 0.0)})
    p.finish({})
    return b.finish(e)


_EMITTER2_FLAGS = (("SortPrimsFarZ", 0x10000), ("Unshaded", 0x8000), ("LineEmitter", 0x20000), ("Unfogged", 0x40000),
                   ("ModelSpace", 0x80000), ("XYQuad", 0x100000))
_EMITTER2_FILTERS = ("Blend", "Additive", "Modulate", "Modulate2x", "AlphaKey")
_HEAD_OR_TAIL = ("Head", "Tail", "Both")
_EMITTER2_TRACKS = {"KP2S": "Speed", "KP2R": "Variation", "KP2L": "Latitude", "KP2G": "Gravity", "KP2V": "Visibility",
                    "KP2E": "EmissionRate", "KP2N": "Width", "KP2W": "Length"}


def _w_emitter2(e: dict, v: int) -> list[str]:
    colors = e["segment_color"]
    fields = [f"static Speed {_f(e['speed'])},", f"static Variation {_f(e['variation'])},",
              f"static Latitude {_f(e['latitude'])},", f"static Gravity {_f(e['gravity'])},"]
    fields += ["Squirt,"] if e["squirt"] == 1 else []
    fields += [f"LifeSpan {_f(e['lifespan'])},", f"static EmissionRate {_f(e['emission_rate'])},",
               f"static Width {_f(e['width'])},", f"static Length {_f(e['length'])},"]
    fields += [f"{_EMITTER2_FILTERS[e['filter_mode']]},"] if e["filter_mode"] < len(_EMITTER2_FILTERS) else []
    fields += [f"Rows {e['rows']},", f"Columns {e['columns']},"]
    fields += [f"{_HEAD_OR_TAIL[e['head_or_tail']]},"] if e["head_or_tail"] < 3 else []
    fields += [f"TailLength {_f(e['tail_length'])},", f"Time {_f(e['time'])},"]
    fields += _blk("SegmentColor", [f"Color {_rgb(colors[i:i + 3])}," for i in (0, 3, 6)])
    fields += [f"Alpha {_vec(e['segment_alpha'])},", f"ParticleScaling {_vec(e['segment_scaling'])},",
               f"LifeSpanUVAnim {_vec(e['head_intervals'][:3])},", f"DecayUVAnim {_vec(e['head_intervals'][3:])},",
               f"TailUVAnim {_vec(e['tail_intervals'][:3])},", f"TailDecayUVAnim {_vec(e['tail_intervals'][3:])},",
               f"TextureID {_id(e['texture_id'])},"]
    fields += [f"ReplaceableId {e['replaceable_id']},"] if e["replaceable_id"] else []
    fields += [f"PriorityPlane {e['priority_plane']},"] if e["priority_plane"] else []
    return _emit(f"ParticleEmitter2 {_q(e['node']['name'])}",
                 _node_object_lines(e, _EMITTER2_TRACKS, fields, _EMITTER2_FLAGS), e, _r_emitter2, v)


def _r_emitter2(atoms, body, v: int) -> dict:
    b = _Block(body, "ParticleEmitter2")
    e = _node_object(atoms, b, 0x1000, _EMITTER2_TRACKS, _EMITTER2_FLAGS)
    colors = _Block(next((block for _, block in b.all("SegmentColor")), []), "SegmentColor")
    segment = [c for _, block in colors.all("Color") for c in [_float(t) for t in _flat(block)][::-1]]
    colors.finish({})
    e.update({"speed": b.value("static Speed", _float, 0.0), "variation": b.value("static Variation", _float, 0.0),
              "latitude": b.value("static Latitude", _float, 0.0), "gravity": b.value("static Gravity", _float, 0.0),
              "lifespan": b.value("LifeSpan", _float, 0.0), "emission_rate": b.value("static EmissionRate", _float, 0.0),
              "width": b.value("static Width", _float, 0.0), "length": b.value("static Length", _float, 0.0),
              "filter_mode": b.choice(_EMITTER2_FILTERS), "rows": b.value("Rows", _u32, 1),
              "columns": b.value("Columns", _u32, 1), "head_or_tail": b.choice(_HEAD_OR_TAIL),
              "tail_length": b.value("TailLength", _float, 0.0), "time": b.value("Time", _float, 0.0),
              "segment_color": segment if len(segment) == 9 else [1.0] * 9,
              "segment_alpha": b.value("Alpha", _u32, [255] * 3), "segment_scaling": b.value("ParticleScaling", _float, [1.0] * 3),
              "head_intervals": b.value("LifeSpanUVAnim", _u32, [0] * 3) + b.value("DecayUVAnim", _u32, [0] * 3),
              "tail_intervals": b.value("TailUVAnim", _u32, [0] * 3) + b.value("TailDecayUVAnim", _u32, [0] * 3),
              "texture_id": b.value("TextureID", _u32, 0), "squirt": 1 if b.has("Squirt") else 0,
              "priority_plane": b.value("PriorityPlane", _i32, 0), "replaceable_id": b.value("ReplaceableId", _u32, 0)})
    return b.finish(e)


_RIBBON_TRACKS = {"KRHA": "HeightAbove", "KRHB": "HeightBelow", "KRAL": "Alpha", "KRCO": "Color", "KRTX": "TextureSlot",
                  "KRVS": "Visibility"}


def _w_ribbon(r: dict, v: int) -> list[str]:
    fields = [f"static HeightAbove {_f(r['height_above'])},", f"static HeightBelow {_f(r['height_below'])},",
              f"static Alpha {_f(r['alpha'])},", f"static Color {_rgb(r['color'])},",
              f"static TextureSlot {r['texture_slot']},", f"EmissionRate {r['emission_rate']},",
              f"LifeSpan {_f(r['lifespan'])},"]
    fields += [f"Gravity {_f(r['gravity'])},"] if not _zero([r["gravity"]]) else []
    fields += [f"Rows {r['rows']},", f"Columns {r['columns']},", f"MaterialID {r['material_id']},"]
    return _emit(f"RibbonEmitter {_q(r['node']['name'])}", _node_object_lines(r, _RIBBON_TRACKS, fields), r, _r_ribbon, v)


def _r_ribbon(atoms, body, v: int) -> dict:
    b = _Block(body, "RibbonEmitter")
    r = _node_object(atoms, b, 0x4000, _RIBBON_TRACKS)
    r.update({"height_above": b.value("static HeightAbove", _float, 0.0),
              "height_below": b.value("static HeightBelow", _float, 0.0), "alpha": b.value("static Alpha", _float, 1.0),
              "color": b.value("static Color", _float, [1.0] * 3)[::-1], "lifespan": b.value("LifeSpan", _float, 0.0),
              "texture_slot": b.value("static TextureSlot", _u32, 0), "emission_rate": b.value("EmissionRate", _u32, 0),
              "rows": b.value("Rows", _u32, 1), "columns": b.value("Columns", _u32, 1),
              "material_id": b.value("MaterialID", _u32, 0), "gravity": b.value("Gravity", _float, 0.0)})
    return b.finish(r)


_CORN_FLAGS = (("SortPrimsFarZ", 0x10000), ("Unshaded", 0x8000), ("Unfogged", 0x40000))
_CORN_TRACKS = {"KPPL": "LifeSpan", "KPPE": "EmissionRate", "KPPS": "Speed", "KPPC": "Color", "KPPA": "Alpha",
                "KPPV": "Visibility"}


def _w_corn(c: dict, v: int) -> list[str]:
    fields = [f"static LifeSpan {_f(c['lifespan'])},", f"static EmissionRate {_f(c['emission_rate'])},",
              f"static Speed {_f(c['speed'])},", f"static Color {_vec(c['color'])},", f"static Alpha {_f(c['alpha'])},"]
    fields += [f"ReplaceableId {c['replaceable_id']},"] if c["replaceable_id"] else []
    fields += [f"Path {_q(c['path'])},"] if c["path"] else []
    fields += [f"AnimVisibilityGuide {_q(c['animation_visibility_guide'])},"] if c["animation_visibility_guide"] else []
    return _emit(f"ParticleEmitterPopcorn {_q(c['node']['name'])}", _node_object_lines(c, _CORN_TRACKS, fields, _CORN_FLAGS),
                 c, _r_corn, v)


def _r_corn(atoms, body, v: int) -> dict:
    b = _Block(body, "ParticleEmitterPopcorn")
    c = _node_object(atoms, b, 0x1000, _CORN_TRACKS, _CORN_FLAGS)
    c.update({"lifespan": b.value("static LifeSpan", _float, 0.0), "emission_rate": b.value("static EmissionRate", _float, 0.0),
              "speed": b.value("static Speed", _float, 0.0), "color": b.value("static Color", _float, [1.0] * 3),
              "alpha": b.value("static Alpha", _float, 1.0), "replaceable_id": b.value("ReplaceableId", _u32, 0),
              "path": _string(b, "Path"), "animation_visibility_guide": _string(b, "AnimVisibilityGuide")})
    return b.finish(c)


def _w_camera(c: dict, v: int) -> list[str]:
    own = [t for t in c["tracks"] if t["tag"] != "KTTR"]
    lines = [f"Position {_vec(c['position'])},"] + _tracks_lines(own, {"KCTR": "Translation", "KCRL": "Rotation"})
    lines += [f"FieldOfView {_f(c['field_of_view'])},", f"FarClip {_f(c['far_clipping_plane'])},",
              f"NearClip {_f(c['near_clipping_plane'])},"]
    lines += _blk("Target", [f"Position {_vec(c['target_position'])},"]
                  + _tracks_lines([t for t in c["tracks"] if t["tag"] == "KTTR"], {"KTTR": "Translation"}))
    return _emit(f"Camera {_q(c['name'])}", lines, c, _r_camera, v)


def _r_camera(atoms, body, v: int) -> dict:
    b = _Block(body, "Camera")
    target = _Block(next((block for _, block in b.all("Target")), []), "Target")
    c = {"size_flags": 0, "name": _name(atoms), "position": b.value("Position", _float, [0.0] * 3),
         "field_of_view": b.value("FieldOfView", _float, 0.0), "far_clipping_plane": b.value("FarClip", _float, 0.0),
         "near_clipping_plane": b.value("NearClip", _float, 0.0),
         "target_position": target.value("Position", _float, [0.0] * 3),
         "tracks": b.tracks({"Translation": "KCTR", "Rotation": "KCRL"}) + target.tracks({"Translation": "KTTR"})}
    target.finish({})
    return b.finish(c)


def _w_event(e: dict, v: int) -> list[str]:
    lines = _node_lines(e["node"]) + _tracks_lines(e["node"]["tracks"], _NODE_TRACKS)
    if "frames" in e:
        gs = [f"GlobalSeqId {e['global_sequence']},"] if e["global_sequence"] != -1 else []
        lines += _blk(f"EventTrack {len(e['frames'])}", gs + [f"{f}," for f in e["frames"]])
    return _emit(f"EventObject {_q(e['node']['name'])}", lines, e, _r_event, v)


def _r_event(atoms, body, v: int) -> dict:
    b = _Block(body, "EventObject")
    e = _node_object(atoms, b, 0x400, {})
    if e.pop("tracks"):
        raise FormatError("MDL EventObject holds only node tracks")
    for _, block in b.all("EventTrack")[:1]:
        tokens = _flat(block)
        global_sequence = tokens[:1] == ["GlobalSeqId"]
        e["global_sequence"] = _i32(tokens[1]) if global_sequence else -1
        e["frames"] = [_u32(t) for t in tokens[2 if global_sequence else 0:]]
    return b.finish(e)


_SHAPES = ("Box", "Plane", "Sphere", "Cylinder")


def _w_collision(c: dict, v: int) -> list[str]:
    lines = _node_lines(c["node"]) + ([f"{_SHAPES[c['type']]},"] if c["type"] < 4 else [])
    lines += _rows("Vertices", c["vertices"], 3)
    if "radius" in c:
        lines.append(f"BoundsRadius {_f(c['radius'])},")
    lines += _tracks_lines(c["node"]["tracks"], _NODE_TRACKS)
    return _emit(f"CollisionShape {_q(c['node']['name'])}", lines, c, _r_collision, v)


def _r_collision(atoms, body, v: int) -> dict:
    b = _Block(body, "CollisionShape")
    c = _node_object(atoms, b, 0x2000, {})
    if c.pop("tracks"):
        raise FormatError("MDL CollisionShape holds only node tracks")
    c["type"] = b.choice(_SHAPES)
    c["vertices"] = b.value("Vertices", _float, [0.0] * (3 if c["type"] == 2 else 6))
    if c["type"] in (2, 3):
        c["radius"] = b.value("BoundsRadius", _float, 0.0)
    return b.finish(c)


def _w_face_effect(f: dict, v: int) -> list[str]:
    return _emit(f"FaceFX {_q(f['type'])}", [f"Path {_q(f['path'])},"], f, _r_face_effect, v)


def _r_face_effect(atoms, body, v: int) -> dict:
    b = _Block(body, "FaceFX")
    return b.finish({"type": _name(atoms), "path": _string(b, "Path")})


# chunk tag -> (MDL keyword, writer, reader) for chunks written as one MDL block per object
_OBJECTS = {
    "GEOS": ("Geoset", _w_geoset, _r_geoset), "GEOA": ("GeosetAnim", _w_geoset_animation, _r_geoset_animation),
    "BONE": ("Bone", _w_bone, _r_bone), "LITE": ("Light", _w_light, _r_light), "HELP": ("Helper", _w_helper, _r_helper),
    "ATCH": ("Attachment", _w_attachment, _r_attachment), "PREM": ("ParticleEmitter", _w_emitter, _r_emitter),
    "PRE2": ("ParticleEmitter2", _w_emitter2, _r_emitter2), "CORN": ("ParticleEmitterPopcorn", _w_corn, _r_corn),
    "RIBB": ("RibbonEmitter", _w_ribbon, _r_ribbon), "CAMS": ("Camera", _w_camera, _r_camera),
    "EVTS": ("EventObject", _w_event, _r_event), "CLID": ("CollisionShape", _w_collision, _r_collision),
    "FAFX": ("FaceFX", _w_face_effect, _r_face_effect),
}
# chunk tag -> (MDL keyword, child keyword, writer, reader) for chunks written as one numbered block
_NUMBERED = {
    "SEQS": ("Sequences", "Anim", _w_sequence, _r_sequence), "TEXS": ("Textures", "Bitmap", _w_texture, _r_texture),
    "MTLS": ("Materials", "Material", _w_material, _r_material),
    "TXAN": ("TextureAnims", "TVertexAnim", _w_texture_animation, _r_texture_animation),
}


def serialize(model: dict) -> bytes:
    """MDL text (UTF-8) for a model from mdx.parse or parse"""
    v = model["version"]
    out = ["// MDL written by wc3mcp", *_blk("Version", [f"FormatVersion {v},"])]
    previous = None
    for tag, value in model["chunks"]:
        if isinstance(value, bytes):
            out.append(f"//@ raw {_json({'tag': tag, 'data': value})}")
        elif tag in _OBJECTS:
            if not value or previous == tag:
                out.append(f"//@ chunk {_json(tag)}")
            for obj in value:
                out += _OBJECTS[tag][1](obj, v)
        elif tag in _NUMBERED:
            word, _, write, _ = _NUMBERED[tag]
            out += _blk(f"{word} {len(value)}", [line for obj in value for line in write(obj, v)])
        elif tag == "MODL":
            out += _w_model(value, v)
        elif tag == "GLBS":
            out += _blk(f"GlobalSequences {len(value)}", [f"Duration {d}," for d in value])
        elif tag == "PIVT":
            out += _rows("PivotPoints", [x for p in value for x in p], 3)
        elif tag == "BPOS":
            out += _blk("BindPose", _rows("Matrices", [x for m in value for x in m], 12))
        else:
            raise FormatError(f"MDL cannot write chunk {tag}")
        previous = tag
    return ("\n".join(out) + "\n").encode("utf-8", "surrogateescape")


def parse(data: bytes | str) -> dict:
    """{"version", "chunks"} like mdx.parse, from MDL text"""
    text = data.decode("utf-8", "surrogateescape") if isinstance(data, bytes) else data
    top = _tree(text.lstrip("﻿"))
    version, chunks = 800, []
    keywords = {word: (tag, read) for tag, (word, _, read) in _OBJECTS.items()}
    numbered = {word: (tag, child, read) for tag, (word, child, _, read) in _NUMBERED.items()}
    for atoms, body in top:
        if type(atoms) is tuple:
            if atoms[1] == "chunk":
                chunks.append([body, []])
            elif atoms[1] == "raw":
                chunks.append([body["tag"], body["data"]])
            else:
                raise FormatError(f"unknown MDL extension {atoms[1]!r}")
            continue
        word = atoms[0]
        if body is None:
            raise FormatError(f"MDL statement {word!r} outside a block")
        if word == "Version":
            b = _Block(body, "Version")
            version = b.value("FormatVersion", _u32, 800)
            b.finish({})
        elif word in keywords:
            tag, read = keywords[word]
            obj = read(atoms, body, version)
            if chunks and chunks[-1][0] == tag:
                chunks[-1][1].append(obj)
            else:
                chunks.append([tag, [obj]])
        elif word in numbered:
            tag, child, read = numbered[word]
            b = _Block(body, word)
            chunks.append([tag, [read([child] + rest, block, version) for rest, block in b.all(child)]])
            b.finish({})
        elif word == "Model":
            chunks.append(["MODL", _r_model(atoms, body, version)])
        elif word == "GlobalSequences":
            b = _Block(body, word)
            chunks.append(["GLBS", [_u32(rest[0]) for rest, _ in b.all("Duration")]])
            b.finish({})
        elif word == "PivotPoints":
            values = [_float(t) for t in _flat(body)]
            chunks.append(["PIVT", [values[i:i + 3] for i in range(0, len(values) - 2, 3)]])
        elif word == "BindPose":
            b = _Block(body, word)
            values = [_float(t) for _, block in b.all("Matrices") for t in _flat(block)]
            chunks.append(["BPOS", [values[i:i + 12] for i in range(0, len(values) - 11, 12)]])
            b.finish({})
        else:
            raise FormatError(f"unknown MDL block {word!r}")
    return {"version": version, "chunks": chunks}
