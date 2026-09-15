"""BLP1 textures (every BLP in the game data): JPEG content, whose four JPEG components hold B, G, R, A with no
colour transform, and paletted content (256 BGRA colours, index plane, alpha plane). parse/serialize keep the file
byte for byte; decode/encode go between files and RGBA images."""
import io
import struct
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, JpegImagePlugin

from .binary import FormatError

MAGIC = b"BLP1"
JPEG, PALETTE = 0, 1
MAX_MIPS = 16


@dataclass
class Blp:
    compression: int                  # JPEG or PALETTE
    alpha_bits: int                   # 0, 1, 4 or 8
    width: int
    height: int
    extra: int = 5                    # picture type; the game's files use 3, 4 or 5
    has_mipmaps: int = 1
    offsets: list[int] = field(default_factory=lambda: [0] * MAX_MIPS)
    sizes: list[int] = field(default_factory=lambda: [0] * MAX_MIPS)
    jpeg_header: bytes = b""          # JPEG content: bytes shared by every mip level
    palette: bytes = b""              # paletted content: 256 x BGRA
    data: bytes = b""                 # everything after the header block, as stored
    data_start: int = 0

    def mip(self, level: int) -> bytes:
        start = self.offsets[level] - self.data_start
        return self.data[start:start + self.sizes[level]]

    @property
    def mip_count(self) -> int:
        return sum(1 for s in self.sizes if s)


def parse(data: bytes) -> Blp:
    if data[:4] != MAGIC:
        raise FormatError(f"not a BLP1 texture (magic {data[:4]!r})")
    if len(data) < 156:
        raise FormatError("truncated BLP header")
    b = Blp(*struct.unpack_from("<6I", data, 4))
    b.offsets = list(struct.unpack_from("<16I", data, 28))
    b.sizes = list(struct.unpack_from("<16I", data, 92))
    if b.compression == JPEG:
        (size,) = struct.unpack_from("<I", data, 156)
        b.jpeg_header, b.data_start = data[160:160 + size], 160 + size
        if len(b.jpeg_header) != size:
            raise FormatError("truncated BLP JPEG header")
    elif b.compression == PALETTE:
        b.palette, b.data_start = data[156:156 + 1024], 156 + 1024
        if len(b.palette) != 1024:
            raise FormatError("truncated BLP palette")
    else:
        raise FormatError(f"unknown BLP compression {b.compression}")
    b.data = data[b.data_start:]
    for level in range(MAX_MIPS):
        if b.sizes[level] and (b.offsets[level] < b.data_start or b.offsets[level] + b.sizes[level] > len(data)):
            raise FormatError(f"BLP mip level {level} lies outside the file")
    return b


def serialize(b: Blp) -> bytes:
    head = MAGIC + struct.pack("<6I", b.compression, b.alpha_bits, b.width, b.height, b.extra, b.has_mipmaps)
    head += struct.pack("<16I", *b.offsets) + struct.pack("<16I", *b.sizes)
    head += struct.pack("<I", len(b.jpeg_header)) + b.jpeg_header if b.compression == JPEG else b.palette
    if len(head) != b.data_start:
        raise FormatError("BLP header size changed; rebuild the texture with encode()")
    return head + b.data


# ---- images ----------------------------------------------------------------------------------------------------
def decode(data: bytes, level: int = 0) -> Image.Image:
    """One mip level as an RGBA image."""
    b = parse(data)
    if not b.sizes[level]:
        raise FormatError(f"BLP has no mip level {level}")
    w, h = max(b.width >> level, 1), max(b.height >> level, 1)
    if b.compression == JPEG:
        jpeg = JpegImagePlugin.JpegImageFile(io.BytesIO(b.jpeg_header + b.mip(level)))
        if jpeg.mode != "CMYK":
            raise FormatError(f"BLP JPEG content has mode {jpeg.mode}, expected four components")
        jpeg.tile = [jpeg.tile[0]._replace(args=("CMYK", ""))]   # raw components, no inversion
        bl, g, r, a = jpeg.split()
        if not b.alpha_bits:
            a = Image.new("L", jpeg.size, 255)
        return Image.merge("RGBA", (r, g, bl, a))
    raw = np.frombuffer(b.mip(level), np.uint8)
    palette = np.frombuffer(b.palette, np.uint8).reshape(256, 4)
    out = np.empty((w * h, 4), np.uint8)
    out[:, :3] = palette[raw[:w * h]][:, 2::-1]          # BGR -> RGB (Pillow wrongly takes alpha from the palette)
    bits, planes = b.alpha_bits, raw[w * h:]
    if bits in (1, 4, 8):
        unpacked = np.unpackbits(planes, bitorder="little")[:w * h * bits]
        if unpacked.size < w * h * bits:
            unpacked = np.concatenate([unpacked, np.ones(w * h * bits - unpacked.size, np.uint8)])
        values = unpacked.reshape(-1, bits) @ (1 << np.arange(bits))
        out[:, 3] = values * 255 // ((1 << bits) - 1)
    else:
        out[:, 3] = 255
    return Image.fromarray(out.reshape(h, w, 4), "RGBA")


def _mips(image: Image.Image, mipmaps: bool) -> list[Image.Image]:
    out = [image]
    while mipmaps and len(out) < MAX_MIPS and (out[-1].width > 1 or out[-1].height > 1):
        prev = out[-1]
        out.append(prev.resize((max(prev.width // 2, 1), max(prev.height // 2, 1)), Image.Resampling.LANCZOS))
    return out


def _jpeg(image: Image.Image, quality: int) -> bytes:
    r, g, bl, a = image.split()
    inverted = Image.merge("CMYK", [x.point(lambda v: 255 - v) for x in (bl, g, r, a)])   # Pillow inverts on save
    buf = io.BytesIO()
    inverted.save(buf, "JPEG", quality=quality, optimize=False, subsampling=0)
    data = buf.getvalue()
    if data[2:4] == b"\xff\xee":   # drop Pillow's Adobe marker: the game's files have none
        data = data[:2] + data[4 + struct.unpack(">H", data[4:6])[0]:]
    return data


def encode(image: Image.Image, compression: int = JPEG, quality: int = 90, mipmaps: bool = True,
           alpha_bits: int | None = None) -> bytes:
    """A BLP1 file for an image: JPEG (like most game icons) or paletted with 8-bit alpha."""
    image = image.convert("RGBA")
    if image.width > 65535 or image.height > 65535:
        raise FormatError("texture too large")
    has_alpha = image.getextrema()[3][0] < 255
    levels = _mips(image, mipmaps)
    b = Blp(compression, (8 if has_alpha else 0) if alpha_bits is None else alpha_bits, image.width, image.height,
            0, 1 if mipmaps else 0)
    b.extra = 4 if b.alpha_bits else 5   # as in the game files
    if compression == JPEG:
        streams = [_jpeg(level, quality) for level in levels]
        common = streams[0]
        for s in streams[1:]:
            n = 0
            while n < min(len(common), len(s)) and common[n] == s[n]:
                n += 1
            common = common[:n]
        # the shared header must end on a segment boundary before the frame header (which holds the size)
        sof = common.find(b"\xff\xc0")
        header = common[:sof] if sof > 0 else common[:2]
        chunks = [s[len(header):] for s in streams]
        b.jpeg_header, b.data_start = header, 160 + len(header)
    elif compression == PALETTE:
        rgb = image.convert("RGB").quantize(256, method=Image.Quantize.MEDIANCUT)
        colors = rgb.getpalette()[:768]
        colors += [0] * (768 - len(colors))
        b.palette = b"".join(bytes((colors[i * 3 + 2], colors[i * 3 + 1], colors[i * 3], 0)) for i in range(256))
        b.data_start = 156 + 1024
        chunks = []
        for level in levels:
            indices = level.convert("RGB").quantize(palette=rgb, dither=Image.Dither.NONE).tobytes()
            alpha = level.getchannel("A").tobytes() if b.alpha_bits == 8 else b""
            chunks.append(indices + alpha)
        if b.alpha_bits not in (0, 8):
            raise FormatError("paletted BLP encoding supports 0 or 8 alpha bits")
    else:
        raise FormatError(f"unknown BLP compression {compression}")
    pos, data = b.data_start, bytearray()
    for level, chunk in enumerate(chunks):
        b.offsets[level], b.sizes[level] = pos, len(chunk)
        data += chunk
        pos += len(chunk)
    b.data = bytes(data)
    return serialize(b)
