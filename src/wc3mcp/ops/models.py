"""Model side of the asset tools: facts, MDX <-> MDL, edits and a software preview of Warcraft III models."""
import copy
import io
import math
import struct

import numpy as np
from PIL import Image, ImageDraw

from ..errors import ToolError
from ..formats import mdl, mdx, texture
from ..formats.binary import FormatError

EXTENSIONS = {".mdx": "mdx", ".mdl": "mdl"}
OPS = ("retexture", "scale", "rename_sequence", "remove_sequence", "team_color", "add_attachment")
# chunks of node objects: flat nodes (bones, helpers) and objects holding a "node"
NODE_TAGS = ("BONE", "LITE", "HELP", "ATCH", "PREM", "PRE2", "CORN", "RIBB", "EVTS", "CLID")
TEAM_COLOR, TEAM_GLOW = 1, 2


def _bad(path: str, message: str, code: str = "bad_value") -> ToolError:
    return ToolError(code, f"{path}: {message}", path=path)


def is_model(data: bytes, name: str) -> bool:
    suffix = name.replace("\\", "/").rsplit("/", 1)[-1].rpartition(".")[2].lower()
    return data[:4] == mdx.MAGIC or f".{suffix}" in EXTENSIONS


def read(data: bytes, name: str) -> dict:
    try:
        return mdx.parse(data) if data[:4] == mdx.MAGIC else mdl.parse(data)
    except FormatError as e:
        raise ToolError("bad_model", f"{name}: {e}") from e


def write(model: dict, fmt: str) -> bytes:
    try:
        return mdx.serialize(model) if fmt == "mdx" else mdl.serialize(model)
    except (FormatError, KeyError, TypeError, ValueError, OverflowError, struct.error) as e:
        raise ToolError("bad_model", f"the edited model cannot be written: {e}") from e


def items(model: dict, tag: str) -> list:
    return [obj for t, value in model["chunks"] if t == tag and isinstance(value, list) for obj in value]


def _text(value) -> str:
    return value.split(b"\0")[0].decode("utf-8", "replace") if isinstance(value, bytes) else value


def _node(obj: dict) -> dict:
    return obj.get("node", obj)


# ---- facts -----------------------------------------------------------------------------------------------------
def info(model: dict) -> dict:
    header = mdx.chunk(model, "MODL") or {}
    geosets = items(model, "GEOS")
    return {
        "format_version": model["version"], "model_name": _text(header.get("name", "")),
        "extent": {k: header[k] for k in ("minimum", "maximum", "bounds_radius") if k in header},
        "sequences": [{"index": i, "name": _text(s["name"]), "interval": s["interval"],
                       "duration": s["interval"][1] - s["interval"][0], "looping": not s["flags"] & 1,
                       "move_speed": s["move_speed"], "rarity": s["rarity"]} for i, s in enumerate(items(model, "SEQS"))],
        "global_sequences": items(model, "GLBS"),
        "textures": [{"index": i, "path": _text(t["path"]), "replaceable_id": t["replaceable_id"]}
                     for i, t in enumerate(items(model, "TEXS"))],
        "materials": len(items(model, "MTLS")),
        "geosets": [{"index": i, "vertices": len(g["vertices"]) // 3, "triangles": len(g["faces"]) // 3,
                     "material_id": g["material_id"], "lod": g.get("lod", 0)} for i, g in enumerate(geosets)],
        "bones": len(items(model, "BONE")), "helpers": len(items(model, "HELP")), "lights": len(items(model, "LITE")),
        "attachments": [_text(a["node"]["name"]) for a in items(model, "ATCH")],
        "particle_emitters": len(items(model, "PREM")) + len(items(model, "PRE2")) + len(items(model, "CORN")),
        "ribbon_emitters": len(items(model, "RIBB")), "event_objects": [_text(e["node"]["name"]) for e in items(model, "EVTS")],
        "cameras": [_text(c["name"]) for c in items(model, "CAMS")], "collision_shapes": len(items(model, "CLID")),
        "unknown_chunks": [t for t, value in model["chunks"] if isinstance(value, bytes)],
    }


# ---- edits -----------------------------------------------------------------------------------------------------
def _chunk(model: dict, tag: str, before: tuple = ()) -> list:
    """the object list of the first chunk with tag, created (before the first chunk in `before`) when missing"""
    for t, value in model["chunks"]:
        if t == tag:
            return value
    at = next((i for i, (t, _) in enumerate(model["chunks"]) if t in before), len(model["chunks"]))
    model["chunks"].insert(at, [tag, []])
    return model["chunks"][at][1]


def _pick(objects: list, ref, name_of, path: str, what: str) -> int:
    if isinstance(ref, int) and not isinstance(ref, bool):
        if 0 <= ref < len(objects):
            return ref
        raise _bad(path, f"no {what} {ref} (the model has {len(objects)})")
    key = str(ref).replace("/", "\\").lower()
    for i, obj in enumerate(objects):
        if _text(name_of(obj)).replace("/", "\\").lower() == key:
            return i
    names = ", ".join(repr(_text(name_of(o))) for o in objects[:20])
    raise _bad(path, f"no {what} named {ref!r}; the model has {names or 'none'}", "not_found")


def _name(value, path: str, limit: int = 79) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > limit:
        raise _bad(path, f"expected a text of at most {limit} bytes")
    return value


FLT_MAX = 3.4028234663852886e38


def _times(values: list, f: float) -> list:
    """scaled float32 values; the largest float (a common "no limit" value) stays the largest"""
    return [min(max(x * f, -FLT_MAX), FLT_MAX) for x in values]


def _scale_tracks(tracks: list, tags: tuple, f: float) -> None:
    for t in tracks:
        if t["tag"] in tags:
            for key in t["keys"]:
                key[1:] = [_times(value, f) for value in key[1:]]


def _scale(model: dict, f: float) -> None:
    def extent(e):
        e["minimum"], e["maximum"] = _times(e["minimum"], f), _times(e["maximum"], f)
        e["bounds_radius"], = _times([e["bounds_radius"]], f)

    for tag, value in model["chunks"]:
        if tag == "MODL":
            extent(value)
        elif tag == "PIVT":
            value[:] = [_times(p, f) for p in value]
        elif tag == "BPOS":   # 3x4 column matrices: the last column is the translation
            value[:] = [m[:9] + _times(m[9:], f) for m in value]
    for s in items(model, "SEQS"):
        extent(s)
    for g in items(model, "GEOS"):
        g["vertices"] = _times(g["vertices"], f)
        extent(g["extent"])
        for e in g["sequence_extents"]:
            extent(e)
    for tag in NODE_TAGS:
        for obj in items(model, tag):
            _scale_tracks(_node(obj)["tracks"], ("KGTR",), f)
    for tag, fields, tracks in (("PRE2", ("speed", "gravity", "width", "length"), ("KP2S", "KP2G", "KP2N", "KP2W")),
                                ("PREM", ("speed", "gravity"), ("KPES", "KPEG")),
                                ("RIBB", ("height_above", "height_below", "gravity"), ("KRHA", "KRHB")),
                                ("CORN", ("speed",), ("KPPS",)),
                                ("LITE", ("attenuation",), ("KLAS", "KLAE")),
                                ("CAMS", ("far_clipping_plane", "near_clipping_plane", "position", "target_position"),
                                 ("KCTR", "KTTR")),
                                ("CLID", ("vertices", "radius"), ())):
        for obj in items(model, tag):
            for field in fields:
                if field in obj:
                    obj[field] = _times(obj[field], f) if isinstance(obj[field], list) else _times([obj[field]], f)[0]
            _scale_tracks(obj.get("tracks", []), tracks, f)


def _team_color(model: dict, index: int, path: str) -> None:
    materials = _chunk(model, "MTLS")
    if not 0 <= index < len(materials):
        raise _bad(path, f"no material {index} (the model has {len(materials)})")
    textures = _chunk(model, "TEXS", ("MTLS", "GEOS"))
    tc = next((i for i, t in enumerate(textures) if t["replaceable_id"] == TEAM_COLOR), None)
    if tc is None:
        textures.append({"replaceable_id": TEAM_COLOR, "path": "", "flags": 0})
        tc = len(textures) - 1
    layers = materials[index]["layers"]
    if not layers:
        raise _bad(path, f"material {index} has no layers")
    first = layers[0]
    if first.get("hd"):   # Reforged shader layer: texture slot 4 is the team colour
        slot = next((t for t in first["textures"] if t["semantic"] == 4), None)
        if slot is None:
            first["textures"].append({"texture_id": tc, "semantic": 4, "tracks": []})
        else:
            slot["texture_id"] = tc
        return
    used = [t["texture_id"] for layer in layers for t in layer.get("textures", [])] or [l["texture_id"] for l in layers]
    if tc in used:
        return
    layer = copy.deepcopy(first)   # the game's pattern: an unshaded team colour layer under a blended texture layer
    layer.update({"filter_mode": 0, "flags": 1, "texture_animation_id": mdx.NO_ID, "alpha": 1.0, "tracks": []})
    if "textures" in layer:
        layer["textures"] = [{"texture_id": tc, "semantic": 0, "tracks": []}]
    else:
        layer["texture_id"] = tc
    if first["filter_mode"] in (0, 1):
        first["filter_mode"] = 2
    layers.insert(0, layer)


def _add_attachment(model: dict, op: dict, path: str) -> dict:
    name = _name(op["name"], path + ".name")
    nodes = [_node(obj) for tag in NODE_TAGS for obj in items(model, tag)]
    parent = op.get("parent")
    if parent is None:
        parent_id = mdx.NO_ID
    else:
        parent_id = nodes[_pick(nodes, parent, lambda n: n["name"], path + ".parent", "node")]["object_id"] \
            if isinstance(parent, str) else int(parent)
        if isinstance(parent, int) and parent_id not in {n["object_id"] for n in nodes}:
            raise _bad(path + ".parent", f"no node with object id {parent}")
    position = [float(x) for x in op.get("position", [0, 0, 0])]
    if len(position) != 3:
        raise _bad(path + ".position", "expected [x, y, z]")
    new_id = max((n["object_id"] for n in nodes), default=-1) + 1
    attachments = _chunk(model, "ATCH", ("PIVT", "PREM", "PRE2", "CORN", "RIBB", "CAMS", "EVTS", "CLID", "FAFX", "BPOS"))
    attachments.append({"node": {"name": name, "object_id": new_id, "parent_id": parent_id, "flags": 0x800, "tracks": []},
                        "path": _name(op.get("path", ""), path + ".path", 259),
                        "attachment_id": max((a["attachment_id"] for a in attachments), default=-1) + 1, "tracks": []})
    pivots = _chunk(model, "PIVT", ("PREM", "PRE2", "CORN", "RIBB", "CAMS", "EVTS", "CLID", "FAFX", "BPOS"))
    pivots.extend([[0.0] * 3 for _ in range(new_id - len(pivots))])
    pivots.insert(new_id, position)
    for tag, value in model["chunks"]:
        if tag == "BPOS" and len(value) >= new_id:
            value.insert(new_id, [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0] + position)
    return {"object_id": new_id}


def apply(model: dict, ops: list) -> list[dict]:
    """edit the model in place; returns per-op notes"""
    if not isinstance(ops, list):
        raise ToolError("bad_op", "ops must be a list", hint='[{"op": "scale", "factor": 1.5}]')
    notes = []
    for i, op in enumerate(ops):
        path = f"ops[{i}]"
        kind = op.get("op") if isinstance(op, dict) else None
        note = {}
        try:
            if kind == "retexture":
                textures = _chunk(model, "TEXS")
                index = _pick(textures, op["texture"], lambda t: t["path"], path + ".texture", "texture")
                new = _name(op["path"], path + ".path", 259)
                textures[index]["path"] = new
                textures[index]["replaceable_id"] = int(op.get("replaceable_id", 0 if new else textures[index]["replaceable_id"]))
                note = {"texture": index}
            elif kind == "scale":
                factor = float(op["factor"])
                if not 0 < factor <= 1000:
                    raise _bad(path + ".factor", "expected a factor above 0 and at most 1000")
                _scale(model, factor)
            elif kind in ("rename_sequence", "remove_sequence"):
                sequences = _chunk(model, "SEQS")
                index = _pick(sequences, op["sequence"], lambda s: s["name"], path + ".sequence", "sequence")
                if kind == "rename_sequence":
                    sequences[index]["name"] = _name(op["name"], path + ".name")
                else:
                    for g in items(model, "GEOS"):
                        if len(g["sequence_extents"]) == len(sequences):
                            del g["sequence_extents"][index]
                    del sequences[index]
                note = {"sequence": index}
            elif kind == "team_color":
                _team_color(model, int(op["material"]), path + ".material")
            elif kind == "add_attachment":
                note = _add_attachment(model, op, path)
            else:
                raise ToolError("bad_op", f"{path}: unknown model op {kind!r}", hint=", ".join(OPS))
        except (KeyError, TypeError, ValueError) as e:
            raise _bad(path, f"missing or invalid argument ({e})") from e
        except ToolError as e:
            e.details.setdefault("op_index", i)
            raise
        notes.append({"op": kind, **note})
    return notes


# ---- preview ---------------------------------------------------------------------------------------------------
_REPLACEABLE = {TEAM_COLOR: (255, 3, 3, 255)}


def _layer_texture(layer: dict) -> int:
    diffuse = [t["texture_id"] for t in layer.get("textures", []) if t["semantic"] == 0]
    return diffuse[0] if diffuse else layer["texture_id"]


def _hidden_geosets(model: dict) -> set[int]:
    """geosets whose geoset animation alpha is below one half at the start of the first Stand sequence (death and
    birth pieces)"""
    sequences = items(model, "SEQS")
    stand = next((s for s in sequences if _text(s["name"]).lower().startswith("stand")), sequences[0] if sequences else None)
    start, end = stand["interval"] if stand else (0, 0)
    hidden = set()
    for a in items(model, "GEOA"):
        alpha = a["alpha"]
        for t in a["tracks"]:
            if t["tag"] == "KGAO":
                keys = t["keys"] if t["global_sequence"] >= 0 else [k for k in t["keys"] if start <= k[0] <= end]
                if keys:
                    alpha = next((k for k in reversed(keys) if k[0] <= start), keys[0])[1][0]
        if alpha < 0.5:
            hidden.add(a["geoset_id"])
    return hidden


def preview(model: dict, size: int, find_texture) -> bytes:
    """PNG of the geosets (level of detail 0) seen from the front left, textured when the textures are found.
    find_texture(path) -> bytes or None."""
    textures, materials = items(model, "TEXS"), items(model, "MTLS")
    cache: dict[int, np.ndarray | None] = {}

    def texels(index: int):
        if index not in cache:
            cache[index] = None
            t = textures[index] if 0 <= index < len(textures) else None
            if t is not None and not t["replaceable_id"] and t["path"]:
                data = find_texture(_text(t["path"]))
                if data:
                    try:
                        image = texture.decode(data, _text(t["path"]))
                        image.thumbnail((256, 256))
                        cache[index] = np.asarray(image.convert("RGBA")).astype(float)
                    except (FormatError, OSError, ValueError):
                        pass
        return cache[index]

    yaw, pitch = math.radians(-35), math.radians(18)
    toward = np.array([math.cos(yaw) * math.cos(pitch), math.sin(yaw) * math.cos(pitch), math.sin(pitch)])
    right = np.cross(-toward, [0, 0, 1])
    right /= np.linalg.norm(right)
    up = np.cross(right, -toward)
    light = toward + np.array([0.0, 0.3, 0.6])
    light /= np.linalg.norm(light)
    hidden = _hidden_geosets(model)
    polygons, depths, colors = [], [], []
    for number, g in enumerate(items(model, "GEOS")):
        if g.get("lod", 0) != 0 or not g["vertices"] or number in hidden:
            continue
        material = materials[g["material_id"]] if g["material_id"] < len(materials) else {"layers": []}
        layers = material["layers"]
        if layers and layers[0]["filter_mode"] >= 3:   # additive and modulated glows
            continue
        v = np.array(g["vertices"], dtype=float).reshape(-1, 3)
        faces, pos, tris = g["faces"], 0, []
        for kind, count in zip(g["face_types"], g["face_groups"]):
            if kind == 4:
                tris += faces[pos:pos + count - count % 3]
            pos += count
        if not tris:
            continue
        tri = np.array(tris, dtype=np.int64).reshape(-1, 3)
        tri = tri[(tri < len(v)).all(1)]
        uv = np.array(g["uvs"][0], dtype=float).reshape(-1, 2) if g["uvs"] else np.zeros((len(v), 2))
        centre_uv = uv[tri].mean(1) if len(uv) == len(v) else np.zeros((len(tri), 2))
        rgba = np.full((len(tri), 4), [150.0, 150.0, 150.0, 255.0])
        for n, layer in enumerate(layers):
            index = _layer_texture(layer)
            t = textures[index] if 0 <= index < len(textures) else None
            if t is not None and t["replaceable_id"] == TEAM_GLOW:
                continue
            if t is not None and t["replaceable_id"] in _REPLACEABLE:
                sample = np.tile(np.array(_REPLACEABLE[t["replaceable_id"]], dtype=float), (len(tri), 1))
            else:
                image = texels(index)
                if image is None:
                    continue
                h, w = image.shape[:2]
                x = (np.mod(centre_uv[:, 0], 1.0) * (w - 1)).astype(int)
                y = (np.mod(centre_uv[:, 1], 1.0) * (h - 1)).astype(int)
                sample = image[y, x]
            if n == 0:
                rgba = sample.copy()
            else:
                a = sample[:, 3:] / 255
                rgba[:, :3] = rgba[:, :3] * (1 - a) + sample[:, :3] * a
        if layers and layers[0]["filter_mode"] == 1:   # alpha tested: drop the transparent parts
            keep = rgba[:, 3] >= 128
            tri, rgba = tri[keep], rgba[keep]
        corners = v[tri]
        normal = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
        length = np.linalg.norm(normal, axis=1)
        shade = 0.4 + 0.6 * np.abs((normal / np.maximum(length, 1e-9)[:, None]) @ light)
        polygons.append(np.stack([corners @ right, -(corners @ up)], -1))
        depths.append(corners.mean(1) @ toward)
        colors.append(np.clip(rgba[:, :3] * shade[:, None], 0, 255).astype(np.uint8))
    if not polygons:
        raise ToolError("bad_value", "the model has no geometry to draw", hint="effects made only of particles show nothing")
    points, depth, color = np.concatenate(polygons), np.concatenate(depths), np.concatenate(colors)
    scale = 2 * size
    low, high = points.reshape(-1, 2).min(0), points.reshape(-1, 2).max(0)
    fit = 0.9 * scale / max(float((high - low).max()), 1e-6)
    points = (points - (low + high) / 2) * fit + scale / 2
    canvas = Image.new("RGB", (scale, scale), (58, 62, 72))
    draw = ImageDraw.Draw(canvas)
    for i in np.argsort(depth):
        draw.polygon([tuple(p) for p in points[i]], fill=tuple(int(c) for c in color[i]))
    out = io.BytesIO()
    canvas.resize((size, size), Image.Resampling.LANCZOS).save(out, "PNG")
    return out.getvalue()
