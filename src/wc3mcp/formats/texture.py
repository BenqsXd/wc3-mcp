"""Texture files by content: BLP1 (blp.py), DDS, TGA, PNG and JPEG (Pillow) -> info, RGBA image, and back."""
import io
import struct

from PIL import Image

from . import blp
from .binary import FormatError

FORMATS = ("blp", "dds", "tga", "png", "jpg")
DDS_FORMATS = {"dxt1": "DXT1", "dxt5": "DXT5", "uncompressed": None}
_SRGB = {72: 71, 78: 77, 99: 98}   # DXGI sRGB block formats Pillow lacks -> the same blocks as UNORM


def kind(data: bytes, name: str = "") -> str:
    if data[:4] == blp.MAGIC:
        return "blp"
    if data[:4] == b"DDS ":
        return "dds"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if name.lower().endswith(".tga") or len(data) >= 18 and data[2] in (2, 3, 10, 11) and data[1] == 0:
        return "tga"
    raise FormatError("not a texture this tool reads (BLP1, DDS, TGA, PNG or JPEG)")


def _dds_header(data: bytes) -> dict:
    if len(data) < 128:
        raise FormatError("truncated DDS header")
    height, width, _, _, mips = struct.unpack_from("<5I", data, 12)
    fourcc = data[84:88]
    out = {"width": width, "height": height, "mipmaps": max(mips, 1),
           "compression": fourcc.decode("latin-1").strip("\0") if fourcc.strip(b"\0") else "uncompressed"}
    if fourcc == b"DX10" and len(data) >= 148:
        out["compression"] = f"DXGI {struct.unpack_from('<I', data, 128)[0]}"
    return out


def info(data: bytes, name: str = "") -> dict:
    k = kind(data, name)
    if k == "blp":
        b = blp.parse(data)
        return {"format": "blp", "version": "BLP1", "width": b.width, "height": b.height, "mipmaps": b.mip_count,
                "compression": "jpeg" if b.compression == blp.JPEG else "palette", "alpha_bits": b.alpha_bits}
    if k == "dds":
        out = {"format": "dds", **_dds_header(data)}
    else:
        image = Image.open(io.BytesIO(data))
        out = {"format": k, "width": image.width, "height": image.height, "mipmaps": 1, "mode": image.mode}
        if k == "tga":
            out["compression"] = "rle" if image.info.get("compression") == "tga_rle" else "none"
    return out


def decode(data: bytes, name: str = "") -> Image.Image:
    """The top mip level as RGBA."""
    k = kind(data, name)
    if k == "blp":
        return blp.decode(data)
    if k == "dds" and data[84:88] == b"DX10" and len(data) >= 132:
        dxgi = struct.unpack_from("<I", data, 128)[0]
        if dxgi in _SRGB:
            data = data[:128] + struct.pack("<I", _SRGB[dxgi]) + data[132:]
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (OSError, ValueError, NotImplementedError) as e:
        raise FormatError(f"cannot decode this {k.upper()} texture: {e}") from e
    return image.convert("RGBA")


def encode(image: Image.Image, fmt: str, compression: str | None = None, quality: int = 90,
           mipmaps: bool = True) -> bytes:
    """blp (compression jpeg | palette), dds (dxt1 | dxt5 | uncompressed), tga (rle | none), png, jpg."""
    image = image.convert("RGBA")
    buf = io.BytesIO()
    if fmt == "blp":
        if compression not in (None, "jpeg", "palette"):
            raise FormatError("BLP compression is jpeg or palette")
        return blp.encode(image, blp.PALETTE if compression == "palette" else blp.JPEG, quality, mipmaps)
    if fmt == "dds":
        if compression not in (None, *DDS_FORMATS):
            raise FormatError(f"DDS compression is one of {', '.join(DDS_FORMATS)}")
        # ponytail: Pillow writes the top level only; the game builds missing mip levels itself
        pixel = DDS_FORMATS[compression or "dxt5"]
        image.save(buf, "DDS", **({"pixel_format": pixel} if pixel else {}))
    elif fmt == "tga":
        image.save(buf, "TGA", rle=compression == "rle")
    elif fmt == "png":
        image.save(buf, "PNG")
    elif fmt == "jpg":
        image.convert("RGB").save(buf, "JPEG", quality=quality)
    else:
        raise FormatError(f"unknown texture format {fmt!r}; use one of {', '.join(FORMATS)}")
    return buf.getvalue()
