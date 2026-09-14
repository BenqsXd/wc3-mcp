import pytest

from corpus import open_sample, sample_map_ids
from wc3mcp.formats import objmods
from wc3mcp.formats.binary import FormatError
from wc3mcp.formats.objmods import STRING, UNREAL, ZERO_ID, Mod, ObjectEntry, ObjectMods


def test_constructed_roundtrip_with_and_without_levels():
    om = ObjectMods(3, levels=True, original=[ObjectEntry(b"AHbz", mods=[Mod(b"Hbz1", 0, 7, level=1, pointer=1, end=b"AHbz")])],
                    custom=[ObjectEntry(b"AHbz", b"A000", [Mod(b"anam", STRING, "Big Storm"), Mod(b"acdn", UNREAL, 0.5, 2)])])
    assert objmods.parse(objmods.serialize(om), levels=True) == om
    simple = ObjectMods(2, levels=False, custom=[ObjectEntry(b"hfoo", b"h000", [Mod(b"uhpm", 0, 777)])])
    assert objmods.parse(objmods.serialize(simple), levels=False) == simple


def test_rejects_unsupported_input():
    with pytest.raises(FormatError):
        objmods.parse((1).to_bytes(4, "little") + bytes(8), levels=False)
    two_sets = (3).to_bytes(4, "little") + (1).to_bytes(4, "little") + b"hfoo" + ZERO_ID + (2).to_bytes(4, "little")
    with pytest.raises(FormatError):
        objmods.parse(two_sets + bytes(16), levels=False)
    bad_type = ((2).to_bytes(4, "little") + (1).to_bytes(4, "little") + b"hfoo" + ZERO_ID + (1).to_bytes(4, "little")
                + b"uhpm" + (9).to_bytes(4, "little") + bytes(8) + (0).to_bytes(4, "little"))
    with pytest.raises(FormatError):
        objmods.parse(bad_type, levels=False)


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_roundtrip_is_byte_exact(map_id):
    arc = open_sample(map_id)
    found = 0
    for ext in objmods.EXTENSIONS:
        for prefix in ("war3map", "war3mapSkin"):
            data = arc.read(f"{prefix}.{ext}")
            if data is None:
                continue
            found += 1
            om = objmods.parse(data, levels=ext in objmods.LEVEL_EXTENSIONS)
            assert om.trailing == b"" and objmods.serialize(om) == data, f"{prefix}.{ext}"
    if not found:
        pytest.skip("map has no object data")
