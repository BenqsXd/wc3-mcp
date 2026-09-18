"""Symmetry. A competitive map has to be the same for every player, and mirroring terrain and objects by hand is
where maps quietly become unfair. One op does it for both: build one half or one quadrant properly, then mirror it.

terrain_apply runs on an ops.terrain._Brush, PlacedMirror is mixed into ops.placed._Edit next to the layout ops.
"""
import math

from ..errors import ToolError
from ..formats import w3e
from .elements import _bad, _bool, _int, _num

AXES = ("x", "y", "point", "rot90", "rot180", "rot270")
KEYS = {"axis", "from", "centre"}
TERRAIN_KEYS = {"mirror": KEYS | {"layers"}}
PLACED_KEYS = {"mirror": {"op", *KEYS, "kinds", "owner_map", "replace"}}
LAYERS = ("height", "texture", "cliff", "water", "flags")
FLAG_FIELDS = ("ramp", "blight", "boundary")
MIRROR_KINDS = ("unit", "item", "doodad", "destructible")


def _axis(op: dict, path: str) -> str:
    axis = op.get("axis", "x")
    if axis not in AXES:
        raise _bad(f"{path}.axis", "expected one of: " + ", ".join(AXES))
    return axis


def _centre(op: dict, path: str, bounds) -> tuple[float, float]:
    given = op.get("centre")
    if given is None:
        return (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
    if not isinstance(given, list) or len(given) != 2:
        raise _bad(f"{path}.centre", "expected [x, y]")
    return _num(given[0], f"{path}.centre"), _num(given[1], f"{path}.centre")


def _source(op: dict, path: str, bounds, axis: str, centre) -> tuple[float, float, float, float]:
    """The area that gets copied: what the caller gave, or the half (or quadrant) the axis implies."""
    given = op.get("from")
    if given is not None:
        if not isinstance(given, list) or len(given) != 4:
            raise _bad(f"{path}.from", "expected [left, bottom, right, top]")
        return tuple(_num(v, f"{path}.from") for v in given)
    cx, cy = centre
    if axis == "x":
        return bounds[0], bounds[1], cx, bounds[3]
    if axis == "y":
        return bounds[0], cy, bounds[2], bounds[3]
    return bounds[0], bounds[1], cx, cy      # a rotation copies one quadrant around the centre


def reflect(axis: str, centre, x: float, y: float) -> tuple[float, float]:
    """Where (x, y) lands, and by how much a facing turns with it (the caller adds `turn`)."""
    cx, cy = centre
    dx, dy = x - cx, y - cy
    if axis == "x":
        return cx - dx, y
    if axis == "y":
        return x, cy - dy
    if axis in ("point", "rot180"):
        return cx - dx, cy - dy
    if axis == "rot90":
        return cx - dy, cy + dx
    return cx + dy, cy - dx                   # rot270


def turn(axis: str, angle: float) -> float:
    """The facing a mirrored object keeps. A reflection flips the angle, a rotation adds to it."""
    if axis == "x":
        return (180 - angle) % 360
    if axis == "y":
        return (-angle) % 360
    if axis in ("point", "rot180"):
        return (angle + 180) % 360
    if axis == "rot90":
        return (angle + 90) % 360
    return (angle + 270) % 360


# ---- terrain ---------------------------------------------------------------------------------------------------
def terrain_apply(brush, op: dict, path: str) -> bool:
    """{"op": "mirror", "axis", "from", "centre", "layers"} over the terrain corners. False when not ours."""
    if op.get("op") != "mirror":
        return False
    from .terrain import _bounds, _xy

    t = brush.t
    bounds = _bounds(t)
    axis = _axis(op, path)
    centre = _centre(op, path, bounds)
    left, bottom, right, top = _source(op, path, bounds, axis, centre)
    layers = op.get("layers", list(LAYERS))
    if not isinstance(layers, list) or not set(layers) <= set(LAYERS):
        raise _bad(f"{path}.layers", "expected any of: " + ", ".join(LAYERS))
    source = [(cx, cy) for cx, cy in brush._window(left, bottom, right, top)]
    if not source:
        raise _bad(path, f"the source area covers no terrain corner; the map spans {bounds}")
    if axis in ("rot90", "rot270") and (right - left) != (top - bottom):
        raise ToolError("bad_value", f"{path}: rotating by 90 degrees needs a square source area, not "
                                     f"{right - left:g} by {top - bottom:g}",
                        hint='use "point" for a 180 degree rotation, or square the area')
    written = 0
    for cx, cy in source:
        values = dict(w3e.corner(t, cx, cy))
        x, y = _xy(t, cx, cy)
        mx, my = reflect(axis, centre, x, y)
        tx = int(round((mx - t.offset_x) / 128))
        ty = int(round((my - t.offset_y) / 128))
        if not (0 <= tx < t.width and 0 <= ty < t.height):
            continue
        fields = {}
        if "height" in layers:
            fields["height"] = values["height"]
        if "texture" in layers:
            fields["texture"] = values["texture"]
        if "cliff" in layers:
            fields.update(layer=values["layer"], cliff_texture=values["cliff_texture"])
        if "water" in layers:
            fields.update(water=values["water"], water_level=values["water_level"])
        if "flags" in layers:
            fields.update({flag: values[flag] for flag in FLAG_FIELDS})
        w3e.set_corner(t, tx, ty, **fields)
        if "texture" in layers:
            brush.painted[(tx, ty)] = values["texture"]
        written += 1
    if not written:
        raise ToolError("bad_value", f"{path}: every mirrored corner lands outside the map",
                        hint="check centre and from against the map bounds " + str(bounds))
    return True


# ---- placed objects --------------------------------------------------------------------------------------------
class PlacedMirror:
    """placed_edit's mirror op. Mixed into _Edit, which supplies op_add, op_delete, the terrain and the type checks."""

    def op_mirror(self, op: dict, path: str) -> None:
        bounds = self.playable() or self.whole() or [-4096.0, -4096.0, 4096.0, 4096.0]
        axis = _axis(op, path)
        centre = _centre(op, path, bounds)
        left, bottom, right, top = _source(op, path, bounds, axis, centre)
        if axis in ("rot90", "rot270") and round(right - left) != round(top - bottom):
            raise ToolError("bad_value", f"{path}: rotating by 90 degrees needs a square source area, not "
                                         f"{right - left:g} by {top - bottom:g}",
                            hint='use "point" for a 180 degree rotation, or square the area')
        kinds = op.get("kinds", list(MIRROR_KINDS))
        if isinstance(kinds, str):
            kinds = [kinds]
        if not isinstance(kinds, list) or not set(kinds) <= set(MIRROR_KINDS):
            raise _bad(f"{path}.kinds", "expected any of: " + ", ".join(MIRROR_KINDS))
        owners = op.get("owner_map") or {}
        if not isinstance(owners, dict) or not all(isinstance(v, int) for v in owners.values()):
            raise _bad(f"{path}.owner_map", 'expected {"0": 1, "1": 0}: the owner the copies get')
        owner_map = {}
        for key, value in owners.items():
            try:
                owner_map[int(key)] = _int(value, f"{path}.owner_map", 0, 27)
            except (TypeError, ValueError) as e:
                raise _bad(f"{path}.owner_map", "the keys are player numbers") from e
        replace = _bool(op.get("replace", True), f"{path}.replace")
        # read the source objects before anything is written, so a mirror into an overlapping area still reads the
        # original patch
        rows = []
        for kind in kinds:
            for ref in self._refs_in(kind, lambda x, y: left <= x <= right and bottom <= y <= top, None):
                found, o = self._find(ref, path)
                rows.append((kind, o, self.to_json(kind, o, {})))
        if replace:
            target = reflect_rect(axis, centre, (left, bottom, right, top))
            removed = 0
            for kind in kinds:
                for ref in self._refs_in(kind, lambda x, y: _inside(target, x, y), None):
                    self.op_delete({"op": "delete", "ref": ref}, path)
                    removed += 1
            if removed:
                self.notes.append(f"{path}: {removed} object(s) removed from the mirrored area first")
        made = 0
        for kind, o, doc in rows:
            x, y = reflect(axis, centre, doc["x"], doc["y"])
            # placed_list reports more than add takes (script_name, the resolved name); keep the writable fields
            writable = self._fields(kind) - {"x", "y", "angle"}
            fields = {k: v for k, v in doc.items() if k in writable and v is not None}
            if kind == "start_location":
                fields.pop("type", None)
            add = {"op": "add", "kind": kind, "x": round(x, 1), "y": round(y, 1),
                   "angle": round(turn(axis, doc.get("angle") or 0.0), 1), **fields}
            if "owner" in fields and fields["owner"] in owner_map:
                add["owner"] = owner_map[fields["owner"]]
            self.op_add(add, f"{path}[{made}]")
            made += 1
        self.notes.append(f"{path}: {made} object(s) mirrored ({axis})")


def reflect_rect(axis: str, centre, rect):
    """Where a rectangle lands when it is mirrored: the box around its four mirrored corners."""
    left, bottom, right, top = rect
    points = [reflect(axis, centre, x, y) for x, y in ((left, bottom), (right, bottom), (right, top), (left, top))]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _inside(rect, x: float, y: float) -> bool:
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]
