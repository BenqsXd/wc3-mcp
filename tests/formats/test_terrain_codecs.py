import pytest

from corpus import open_sample, sample_map_ids
from wc3mcp.formats import mmp, w3e, wpm
from wc3mcp.formats.binary import FormatError

LIMITS = {11: 15, 12: 63}


def _terrain(version: int) -> w3e.Terrain:
    return w3e.Terrain(version, "L", 0, [b"Ldrt", b"Lgrs"], [b"CLdi"], 3, 2, -256.0, -128.0,
                       heights=[8192, 8200, -5, 0, 12000, 8192], water=[0x1F00, 0x5F00, 0, 0x3FFF, 0xC000, 1],
                       textures=[0x41, 0x80, 0, 1, 0x1F if version < 12 else 0x3FF, 2],
                       variations=[0, 31, 224, 255, 17, 8], cliffs=[0xF2, 0x02, 0, 0x3F, 0xFF, 0x12])


@pytest.mark.parametrize("version", sorted(w3e.VERSIONS))
def test_terrain_roundtrip(version):
    t = _terrain(version)
    assert w3e.parse(w3e.serialize(t)) == t


@pytest.mark.parametrize("version", sorted(w3e.VERSIONS))
def test_corner_fields_pack_and_unpack(version):
    t = _terrain(version)
    fields = dict(height=-3, water_level=0x3FFF, edge=1, texture=LIMITS[version], ramp=True, blight=False, water=True,
                  boundary=True, ground_variation=31, cliff_variation=7, cliff_texture=15, layer=14)
    w3e.set_corner(t, 2, 1, **fields)
    assert w3e.corner(t, 2, 1) == fields
    assert w3e.parse(w3e.serialize(t)) == t
    before = w3e.corner(t, 1, 1)
    w3e.set_corner(t, 1, 1, blight=True)
    assert w3e.corner(t, 1, 1) == {**before, "blight": True}


def test_set_corner_keeps_unknown_bits_and_rejects_bad_values():
    t = _terrain(12)
    t.textures[0] |= 0x1000
    w3e.set_corner(t, 0, 0, texture=5)
    assert t.textures[0] & 0x1000 and w3e.corner(t, 0, 0)["texture"] == 5
    for bad in ({"texture": 64}, {"height": 40000}, {"layer": 16}, {"ramp": 1}, {"colour": 1}):
        with pytest.raises(FormatError):
            w3e.set_corner(t, 0, 0, **bad)
    with pytest.raises(FormatError):
        w3e.set_corner(_terrain(11), 0, 0, texture=16)
    with pytest.raises(IndexError):
        w3e.corner(t, 3, 0)


def test_terrain_rejects_bad_data():
    data = w3e.serialize(_terrain(12))
    for bad in (b"W3X!" + data[4:], data[:4] + (13).to_bytes(4, "little") + data[8:], data[:-1], data + b"\0"):
        with pytest.raises(FormatError):
            w3e.parse(bad)
    t = _terrain(11)
    t.heights.pop()
    with pytest.raises(FormatError):
        w3e.serialize(t)


def test_pathing_and_minimap_roundtrip():
    pm = wpm.PathingMap(0, 4, 2, bytearray(b"\x00\x02\x08\x40\xc0\x00\x0a\xff"))
    data = wpm.serialize(pm)
    assert wpm.parse(data) == pm
    for bad in (b"XP3W" + data[4:], data[:-1], data + b"\0"):
        with pytest.raises(FormatError):
            wpm.parse(bad)
    mm = mmp.Minimap(0, [mmp.Icon(0, 128, 200, b"\xff\xff\xff\xff"), mmp.Icon(2, 36, 40, b"\x03\x03\xff\xff")])
    assert mmp.parse(mmp.serialize(mm)) == mm
    with pytest.raises(FormatError):
        mmp.parse((1).to_bytes(4, "little") + bytes(4))


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_roundtrip_is_byte_exact(map_id):
    archive = open_sample(map_id)
    data = {n: archive.read(n) for n in ("war3map.w3e", "war3map.wpm", "war3map.mmp", "war3map.shd")}
    terrain = w3e.parse(data["war3map.w3e"])
    assert w3e.serialize(terrain) == data["war3map.w3e"]
    pathing = wpm.parse(data["war3map.wpm"])
    assert wpm.serialize(pathing) == data["war3map.wpm"]
    assert (pathing.width, pathing.height) == (4 * (terrain.width - 1), 4 * (terrain.height - 1))
    assert len(data["war3map.shd"]) == pathing.width * pathing.height
    assert mmp.serialize(mmp.parse(data["war3map.mmp"])) == data["war3map.mmp"]
