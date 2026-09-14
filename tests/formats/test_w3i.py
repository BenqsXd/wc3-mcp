import pytest

from corpus import open_sample, sample_map_ids
from wc3mcp.formats import w3i
from wc3mcp.formats.binary import FormatError

HUMANX01 = "casc:Campaign/Classic/TFT/HumanX01.w3x"


def _sample_info() -> w3i.MapInfo:
    mi = w3i.MapInfo(39, map_version=3, editor_version=6127, game_version=[2, 0, 4, 23839], name="TRIGSTR_001",
                     camera_bounds=[-1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], camera_complements=[1, 2, 3, 4],
                     playable_width=84, playable_height=84, flags=0x1C, script_language=1)
    mi.players.append(w3i.Player(0, 1, 2, 0x41, "TRIGSTR_002", 128.0, -256.0, 2, 0, 0, 1, v39_value=0))
    mi.forces.append(w3i.Force(0x3, 0xFFFFFFFF, "TRIGSTR_003"))
    mi.upgrades.append(w3i.UpgradeChange(1, b"Rhme", 0, 2))
    mi.tech.append(w3i.TechChange(3, b"hfoo"))
    mi.random_unit_tables.append(w3i.RandomUnitTable(0, "Group", [0, 2],
                                                     [(50, [b"hfoo", b"ratf"]), (50, [b"\0\0\0\0", b"ratc"])]))
    mi.random_item_tables.append(w3i.RandomItemTable(1, "Items", [[(100, b"ratf")], [(60, b"ckng"), (40, b"modt")]]))
    return mi


def test_constructed_info_roundtrip_v39_and_v31():
    mi = _sample_info()
    assert w3i.parse(w3i.serialize(mi)) == mi
    mi.version = 31
    mi.players[0].flags = 1
    mi.players[0].v39_value = 1
    assert w3i.parse(w3i.serialize(mi)) == mi


def test_rejects_unknown_versions_and_short_data():
    with pytest.raises(FormatError):
        w3i.parse((40).to_bytes(4, "little") + bytes(100))
    with pytest.raises(FormatError):
        w3i.parse((31).to_bytes(4, "little") + bytes(10))


def test_v39_player_flag_0x40_carries_extra_int():
    if HUMANX01 not in sample_map_ids():
        pytest.skip("Warcraft III install not found")
    info = w3i.parse(open_sample(HUMANX01).read("war3map.w3i"))
    assert info.version == 39
    assert any(p.flags & w3i.PLAYER_FLAG_V39_EXTRA for p in info.players)


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_roundtrip_is_byte_exact(map_id):
    data = open_sample(map_id).read("war3map.w3i")
    info = w3i.parse(data)
    assert info.version in w3i.WRITABLE_VERSIONS
    assert info.trailing == b"" and not info.truncated
    assert w3i.serialize(info) == data
