"""Asset tools: textures (and models, later) from local files, open maps or the game data; results to local files or
map imports."""
import base64
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from ..errors import ToolError
from ..formats import texture
from ..formats.binary import FormatError
from ..project.workspace import write_file
from .imports import imports_edit

TEXTURE_EXTENSIONS = {".blp": "blp", ".dds": "dds", ".tga": "tga", ".png": "png", ".jpg": "jpg", ".jpeg": "jpg"}
ICONS = ("BTN", "DISBTN", "PASBTN", "DISPASBTN")
_HINT = ('source / dest: {"file": "C:/art/icon.png"}, {"map": "<open map path>", "name": "war3mapImported/icon.blp"} or '
         '(source only) {"game": "ReplaceableTextures/CommandButtons/BTNFootman.dds"}')


def _bad(path: str, message: str, code: str = "bad_value") -> ToolError:
    return ToolError(code, f"{path}: {message}", hint=_HINT, path=path)


# ---- sources and destinations ----------------------------------------------------------------------------------
def load(source, project_for, storage) -> tuple[bytes, str]:
    """(bytes, name) of {"file": path}, {"map": path, "name": name} or {"game": path}."""
    if not isinstance(source, dict) or len(source.keys() - {"name"}) != 1:
        raise _bad("source", "expected one of file, map (with name) or game")
    if "file" in source:
        path = Path(str(source["file"]))
        if not path.is_file():
            raise _bad("source.file", f"no file at {path}", "not_found")
        return path.read_bytes(), path.name
    if "map" in source:
        if not isinstance(source.get("name"), str):
            raise _bad("source.name", "give the file name inside the map")
        return project_for(source["map"]).read(source["name"]), source["name"]
    if "game" in source:
        path = str(source["game"])
        full = path if ":" in path else storage.resolve(path.replace("\\", "/"))
        data = storage.read(full) if full else None
        if data is None:
            raise _bad("source.game", f"no game data file {path!r}", "not_found")
        return data, full.rsplit("/", 1)[-1]
    raise _bad("source", "expected one of file, map (with name) or game")


def save(dest, data: bytes, project_for) -> dict:
    if not isinstance(dest, dict):
        raise _bad("dest", "expected {file} or {map, name}")
    if "file" in dest and len(dest) == 1:
        path = Path(str(dest["file"]))
        return {"file": str(path), "backup": write_file(path, data), "size": len(data)}
    if "map" in dest and isinstance(dest.get("name"), str) and len(dest) == 2:
        project = project_for(dest["map"])
        imports_edit(project, [{"op": "add", "path": dest["name"], "content_base64": base64.b64encode(data).decode()}])
        return {"map": dest["map"], "import": dest["name"], "size": len(data)}
    raise _bad("dest", "expected {file} or {map, name}")


def _dest_format(dest, fmt: str | None) -> str:
    if fmt is not None:
        if fmt not in texture.FORMATS:
            raise _bad("format", f"expected one of {', '.join(texture.FORMATS)}")
        return fmt
    name = str(dest.get("file") or dest.get("name") or "") if isinstance(dest, dict) else ""
    found = TEXTURE_EXTENSIONS.get(Path(name.replace("\\", "/")).suffix.lower())
    if found is None:
        raise _bad("format", "give format, or a destination name ending in .blp, .dds, .tga, .png or .jpg")
    return found


def _decode(data: bytes, name: str) -> Image.Image:
    try:
        return texture.decode(data, name)
    except FormatError as e:
        raise ToolError("bad_texture", f"{name}: {e}", hint="models are not supported by this tool yet") from e


# ---- texture edits ---------------------------------------------------------------------------------------------
def _edge_depth(size: int = 64) -> np.ndarray:
    y, x = np.mgrid[0:size, 0:size]
    return np.minimum.reduce([x, y, size - 1 - x, size - 1 - y])


def icon(image: Image.Image, kind: str) -> Image.Image:
    """64x64 command button variants in the style of the game's icons (measured on its BTN / DISBTN textures)."""
    art = np.asarray(image.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)).astype(float)
    depth = _edge_depth()
    out = art.copy()
    if kind.startswith("DIS"):
        lum = art[..., :3] @ [0.299, 0.587, 0.114]
        factor = np.clip(0.098 + (depth - 4) * 0.055, 0, 0.478)   # dark ramp into the border, 0.48 inside
        out[..., :3] = (lum * factor)[..., None]
    if kind in ("BTN",):
        bevel = (depth >= 1) & (depth <= 2)
        y, x = np.mgrid[0:64, 0:64]
        top, left, bottom = y <= 2, x <= 2, y >= 61
        color = np.where(top[..., None], [203, 204, 205], np.where(left[..., None], [188, 188, 191],
                         np.where(bottom[..., None], [95, 96, 97], [110, 111, 112])))
        out[bevel, :3] = color[bevel]
    else:
        out[depth <= 3, :3] = 0                                    # disabled and passive icons have a black frame
        if kind == "PASBTN":
            out[..., :3] *= np.clip(0.15 + (depth - 4) * 0.2, 0, 1)[..., None]
    out[..., 3] = 255
    return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGBA")


def apply(image: Image.Image, ops: list, project_for, storage) -> Image.Image:
    if not isinstance(ops, list):
        raise ToolError("bad_op", "ops must be a list", hint='[{"op": "resize", "width": 64, "height": 64}]')
    for i, op in enumerate(ops):
        path = f"ops[{i}]"
        kind = op.get("op") if isinstance(op, dict) else None
        try:
            if kind == "resize":
                width, height = int(op["width"]), int(op["height"])
                if not (0 < width <= 8192 and 0 < height <= 8192):
                    raise _bad(path, "width and height must be 1-8192")
                image = image.resize((width, height), Image.Resampling.LANCZOS)
            elif kind == "crop":
                box = tuple(int(op[k]) for k in ("left", "top", "right", "bottom"))
                if not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
                    raise _bad(path, f"the box must lie inside the {image.width}x{image.height} image")
                image = image.crop(box)
            elif kind == "grayscale":
                alpha = image.getchannel("A")
                image = ImageOps.grayscale(image).convert("RGBA")
                image.putalpha(alpha)
            elif kind == "brightness":
                alpha = image.getchannel("A")
                image = ImageEnhance.Brightness(image.convert("RGB")).enhance(float(op["factor"])).convert("RGBA")
                image.putalpha(alpha)
            elif kind == "tint":
                r, g, b = (int(c) for c in op["color"])
                strength = float(op.get("strength", 0.5))
                a = np.asarray(image).astype(float)
                a[..., :3] = a[..., :3] * (1 - strength) + np.array([r, g, b]) * strength * (a[..., :3].mean(-1, keepdims=True) / 255)
                image = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")
            elif kind == "overlay":
                data, name = load(op["source"], project_for, storage)
                top = _decode(data, name)
                if "width" in op or "height" in op:
                    top = top.resize((int(op.get("width", top.width)), int(op.get("height", top.height))),
                                     Image.Resampling.LANCZOS)
                opacity = float(op.get("opacity", 1.0))
                if opacity < 1:
                    top.putalpha(top.getchannel("A").point(lambda v: int(v * opacity)))
                base = image.copy()
                base.alpha_composite(top, (int(op.get("x", 0)), int(op.get("y", 0))))
                image = base
            elif kind == "icon":
                if op.get("kind") not in ICONS:
                    raise _bad(path + ".kind", f"expected one of {', '.join(ICONS)}")
                image = icon(image, op["kind"])
            else:
                raise ToolError("bad_op", f"{path}: unknown op {kind!r}",
                                hint="resize, crop, grayscale, brightness, tint, overlay, icon")
        except (KeyError, TypeError, ValueError) as e:
            raise _bad(path, f"missing or invalid argument ({e})") from e
        except ToolError as e:
            e.details.setdefault("op_index", i)
            raise
    return image


# ---- tools -----------------------------------------------------------------------------------------------------
def asset_info(source, project_for, storage) -> dict:
    data, name = load(source, project_for, storage)
    try:
        return {"name": name, "size": len(data), **texture.info(data, name)}
    except FormatError as e:
        raise ToolError("bad_texture", f"{name}: {e}", hint="models are not supported by this tool yet") from e


def asset_convert(source, dest, project_for, storage, fmt: str | None = None, compression: str | None = None,
                  quality: int = 90, mipmaps: bool = True) -> dict:
    return asset_edit(source, dest, [], project_for, storage, fmt, compression, quality, mipmaps)


def asset_edit(source, dest, ops: list, project_for, storage, fmt: str | None = None, compression: str | None = None,
               quality: int = 90, mipmaps: bool = True) -> dict:
    data, name = load(source, project_for, storage)
    fmt = _dest_format(dest, fmt)
    if not 1 <= int(quality) <= 100:
        raise _bad("quality", "expected 1-100")
    image = apply(_decode(data, name), ops, project_for, storage)
    try:
        out = texture.encode(image, fmt, compression, int(quality), mipmaps)
    except FormatError as e:
        raise _bad("compression", str(e)) from e
    return {**save(dest, out, project_for), "format": fmt, "width": image.width, "height": image.height}


def asset_preview(source, project_for, storage, size: int = 256) -> bytes:
    data, name = load(source, project_for, storage)
    image = _decode(data, name)
    if not 16 <= size <= 2048:
        raise _bad("size", "expected 16-2048 pixels")
    if max(image.size) > size:
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
    y, x = np.mgrid[0:image.height, 0:image.width]   # checkerboard behind transparent pixels
    cells = ((x // 8 + y // 8) % 2 == 0)[..., None]
    board = Image.fromarray(np.where(cells, [204, 204, 204, 255], [255, 255, 255, 255]).astype(np.uint8), "RGBA")
    board.alpha_composite(image)
    out = io.BytesIO()
    board.save(out, "PNG")
    return out.getvalue()
