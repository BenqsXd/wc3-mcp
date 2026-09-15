import io
import random

import numpy as np
import pytest
from PIL import Image

from corpus import HAVE_INSTALL, _storage
from wc3mcp.formats import blp, texture
from wc3mcp.formats.binary import FormatError

needs_install = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


def picture(alpha: bool = True) -> Image.Image:
    y, x = np.mgrid[0:64, 0:64]
    a = np.stack([x * 4, y * 4, (x + y) * 2, np.where((x < 16) & (y < 16), 0, 255) if alpha else np.full_like(x, 255)],
                 -1).astype(np.uint8)
    return Image.fromarray(a, "RGBA")


@needs_install
def test_every_game_blp_round_trips_and_decodes():
    s = _storage()
    names = [n for n in s.list("") if n.lower().endswith(".blp")]
    assert len(names) >= 700
    for name in names:
        data = s.read(name)
        b = blp.parse(data)
        assert blp.serialize(b) == data, name
        image = blp.decode(data)
        assert image.size == (b.width, b.height) and image.mode == "RGBA"
        if b.compression == blp.PALETTE:   # Pillow agrees on colour (it reads alpha from the palette, wrongly)
            ours = np.asarray(image)[..., :3]
            assert (ours == np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))).all(), name


@needs_install
def test_game_dds_and_tga_decode():
    s = _storage()
    names = s.list("")
    rng = random.Random(3)
    dds = rng.sample([n for n in names if n.lower().endswith(".dds")], 150)
    dds.append("War3.w3mod:_HD.w3mod:Environment/EnvironmentMap/LordaeronSummer/Day_IBL.dds")   # DXGI 72 (BC1 sRGB)
    for name in dds + [n for n in names if n.lower().endswith(".tga")][:40]:
        data = s.read(name)
        facts = texture.info(data, name)
        assert texture.decode(data, name).size == (facts["width"], facts["height"]), name
    assert texture.info(s.read(dds[-1]))["compression"] == "DXGI 72"


@pytest.mark.parametrize("fmt, compression, tolerance", [
    ("blp", "jpeg", 8), ("blp", "palette", 8), ("dds", "dxt5", 12), ("dds", "uncompressed", 0), ("tga", "rle", 0),
    ("png", None, 0)])
def test_encoders_round_trip(fmt, compression, tolerance):
    image = picture()
    data = texture.encode(image, fmt, compression)
    assert texture.kind(data, "x." + fmt) == fmt
    back = np.asarray(texture.decode(data, "x." + fmt)).astype(int)
    diff = np.abs(back - np.asarray(image).astype(int))
    assert diff[..., :3].mean() <= tolerance and (diff[..., 3] <= max(tolerance, 17)).all()
    facts = texture.info(data, "x." + fmt)
    assert (facts["width"], facts["height"]) == (64, 64)
    if fmt == "blp":
        assert facts["mipmaps"] == 7 and facts["alpha_bits"] == 8 and facts["compression"] == compression


def test_blp_without_alpha_and_errors():
    data = blp.encode(picture(alpha=False))
    b = blp.parse(data)
    assert (b.alpha_bits, b.extra, b.mip_count) == (0, 5, 7)
    assert (np.asarray(blp.decode(data, 6)).shape) == (1, 1, 4)
    with pytest.raises(FormatError):
        texture.kind(b"not a texture at all")
    with pytest.raises(FormatError):
        texture.encode(picture(), "gif")
    with pytest.raises(FormatError):
        blp.parse(b"BLP1" + bytes(20))
