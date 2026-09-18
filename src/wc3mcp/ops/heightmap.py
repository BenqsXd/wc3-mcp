"""Heightmaps in and out. A picture is the one terrain format every other tool speaks, so a map's ground can be
sculpted outside the editor, or driven by something computed, and read back to check the result.

The import is a terrain brush ({"op": "heightmap", ...}); the export hands back a 16-bit grayscale PNG.
"""
import base64
import io
import math
from pathlib import Path

from PIL import Image

from ..errors import ToolError
from ..formats import w3e
from .elements import _bad, _bool, _num

KEYS = {"heightmap": {"source", "content_base64", "amount", "base", "mode", "smooth", "channel"}}
CHANNELS = {"luminance": "L", "red": "R", "green": "G", "blue": "B", "alpha": "A"}
EXPORT_LAYERS = ("height", "cliff", "water")
# what one step of the stored 16-bit height is worth in world units, and the range the format holds
STEP = 0.25
LOW, HIGH = -2048.0, 2048.0


def _image(op: dict, path: str) -> Image.Image:
    if ("source" in op) == ("content_base64" in op):
        raise _bad(path, 'give either "source" (a local image file) or "content_base64"')
    if "source" in op:
        name = op["source"]
        if not isinstance(name, str):
            raise _bad(f"{path}.source", "expected a local file path")
        try:
            data = Path(name).read_bytes()
        except OSError as e:
            raise ToolError("not_found", f"cannot read {name}: {e}", hint="give a local image file",
                            path=f"{path}.source") from e
    else:
        try:
            data = base64.b64decode(op["content_base64"], validate=True)
        except Exception as e:   # noqa: BLE001 - binascii raises several kinds for bad base64
            raise _bad(f"{path}.content_base64", f"not base64: {e}") from e
    try:
        return Image.open(io.BytesIO(data))
    except Exception as e:      # noqa: BLE001 - Pillow raises its own family for unreadable images
        raise ToolError("bad_file", f"this is not an image Pillow can read: {e}",
                        hint="PNG, TGA, BMP and JPEG all work", path=path) from e


def _sample(image: Image.Image, channel: str) -> tuple[Image.Image, float]:
    """The image as one band, and the value that means white (255 or 65535)."""
    if channel == "luminance":
        if image.mode in ("I;16", "I;16B", "I", "F"):
            return image, 65535.0
        return image.convert("L"), 255.0
    band = CHANNELS[channel]
    rgba = image.convert("RGBA")
    return rgba.getchannel(band), 255.0


def apply(brush, op: dict, path: str) -> bool:
    """{"op": "heightmap", "source"|"content_base64", area, "amount", "base", "mode", "smooth", "channel"}."""
    if op.get("op") != "heightmap":
        return False
    from .terrain import _height, _raw, _xy

    channel = op.get("channel", "luminance")
    if channel not in CHANNELS:
        raise _bad(f"{path}.channel", "expected one of: " + ", ".join(CHANNELS))
    mode = op.get("mode", "set")
    if mode not in ("set", "add"):
        raise _bad(f"{path}.mode", 'expected "set" or "add"')
    amount = _num(op.get("amount", 512), f"{path}.amount")
    base = _num(op.get("base", 0), f"{path}.base")
    image, white = _sample(_image(op, path), channel)
    if _bool(op.get("smooth", False), f"{path}.smooth"):
        from PIL import ImageFilter

        image = image.filter(ImageFilter.GaussianBlur(1.5))
    corners, _reach = brush.corners(op, path)
    t = brush.t
    xs = [cx for cx, _cy, _d in corners]
    ys = [cy for _cx, cy, _d in corners]
    cols, rows = max(xs) - min(xs), max(ys) - min(ys)
    x0, y0 = min(xs), min(ys)
    clamped = 0
    for cx, cy, _d in corners:
        # the picture is stretched over the area; its top row is north, as the map is drawn
        u = (cx - x0) / cols if cols else 0.0
        v = 1.0 - ((cy - y0) / rows if rows else 0.0)
        px = min(image.width - 1, max(0, int(round(u * (image.width - 1)))))
        py = min(image.height - 1, max(0, int(round(v * (image.height - 1)))))
        value = base + amount * (image.getpixel((px, py)) / white)
        i = cy * t.width + cx
        height = value if mode == "set" else _height(t.heights[i]) + (value - base)
        if not LOW <= height <= HIGH:
            clamped += 1
            height = min(max(height, LOW), HIGH)
        t.heights[i] = _raw(height)
    if clamped:
        brush.added.setdefault("warnings", []).append(
            f"{path}: {clamped} corner(s) reached the height the terrain format holds ({LOW:g} to {HIGH:g} world "
            "units) and were clamped: lower amount or base")
    return True


def export(terrain, area=None, size: int | None = None, layer: str = "height") -> bytes:
    """A 16-bit grayscale PNG of one terrain layer, north up. height is the ground height, cliff the cliff level,
    water the water surface (black where the ground is dry). Import it back with the amount and base in the result
    of this call's caller to reproduce the terrain."""
    if layer not in EXPORT_LAYERS:
        raise _bad("layer", "expected one of: " + ", ".join(EXPORT_LAYERS))
    from .terrain import _area, _bounds, _height

    left, bottom, right, top = _area(area) if area else _bounds(terrain)
    # the same corner window terrain_get reports, so a picture lines up with the grids
    x0 = max(0, math.ceil((left - terrain.offset_x) / 128))
    y0 = max(0, math.ceil((bottom - terrain.offset_y) / 128))
    x1 = min(terrain.width - 1, math.floor((right - terrain.offset_x) / 128))
    y1 = min(terrain.height - 1, math.floor((top - terrain.offset_y) / 128))
    if x1 < x0 or y1 < y0:
        raise _bad("area", f"the area covers no terrain corner; the map spans {_bounds(terrain)}")
    cols, rows = x1 - x0 + 1, y1 - y0 + 1
    values, low, high = [], None, None
    for cy in range(y1, y0 - 1, -1):          # north first, so the picture is the right way up
        for cx in range(x0, x1 + 1):
            c = w3e.corner(terrain, cx, cy)
            if layer == "height":
                value = _height(c["height"])
            elif layer == "cliff":
                value = float(c["layer"])
            else:
                value = _height(c["water_level"]) if c["water"] else None
            values.append(value)
            if value is not None:
                low = value if low is None else min(low, value)
                high = value if high is None else max(high, value)
    low, high = (0.0, 1.0) if low is None else (low, high)
    span = (high - low) or 1.0
    image = Image.new("I;16", (cols, rows))
    image.putdata([0 if v is None else int(round((v - low) / span * 65535)) for v in values])
    if size:
        scale = size / max(cols, rows)
        image = image.resize((max(1, int(cols * scale)), max(1, int(rows * scale))), Image.Resampling.BILINEAR)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def export_range(terrain, area=None, layer: str = "height") -> dict:
    """The world units black and white stand for in export(), so a round trip can be exact."""
    from .terrain import _area, _bounds, _height

    left, bottom, right, top = _area(area) if area else _bounds(terrain)
    low = high = None
    for cy in range(terrain.height):
        for cx in range(terrain.width):
            x, y = terrain.offset_x + cx * 128, terrain.offset_y + cy * 128
            if not (left <= x <= right and bottom <= y <= top):
                continue
            c = w3e.corner(terrain, cx, cy)
            value = _height(c["height"]) if layer == "height" else (
                float(c["layer"]) if layer == "cliff" else (_height(c["water_level"]) if c["water"] else None))
            if value is None:
                continue
            low = value if low is None else min(low, value)
            high = value if high is None else max(high, value)
    low, high = (0.0, 0.0) if low is None else (low, high)
    return {"layer": layer, "base": round(low, 3), "amount": round(high - low, 3),
            "note": 'import it back with {"op": "heightmap", "base": base, "amount": amount} over the same area'}
