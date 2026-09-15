import struct

import pytest

from corpus import open_sample, sample_map_ids
from wc3mcp.formats import doo, unitsdoo
from wc3mcp.formats.binary import FormatError

SETS = [[(b"pman", 100)], [(b"ckng", 60), (b"\0\0\0\0", 40)]]


def _doodads(version: int, subversion: int) -> doo.DoodadFile:
    tree = doo.Doodad(b"LTlt", 7, -6400.0, 2624.0, 429.5, 4.71875, [1.0, 1.0, 1.25], b"LTlt", 2, 100)
    crate = doo.Doodad(b"LOcg", 0, 704.0, -4096.0, 0.0, 3.5, [0.5, 0.5, 0.5], b"LOcg", 3, 255, item_table=4,
                       item_sets=SETS, editor_id=1482)
    if version >= 12:
        crate.entries = [bytes(range(36))]
    return doo.DoodadFile(version, subversion, [tree, crate], specials=[doo.SpecialDoodad(b"LCc0", 0, 44, 116)])


def _units(version: int, subversion: int) -> unitsdoo.UnitFile:
    scale = [1.0, 1.0, 1.0]
    start = unitsdoo.Unit(b"sloc", 0, 4864.0, -4672.0, 0.0, 4.71875, scale, b"sloc", 2, 0, gold=0,
                          target_acquisition=0.0, hero_level=0, editor_id=1)
    hero = unitsdoo.Unit(b"Hpal", 0, 128.0, 256.0, 12.5, 0.0, scale, b"Hpal", 2, 3, hp=500, gold=0, hero_level=5,
                         inventory=[(0, b"ratf"), (5, b"pghe")], abilities=[(b"AHhb", 1, 2)], item_sets=SETS,
                         waygate=3, color=2, editor_id=7)
    if subversion >= 11:
        hero.item_table, hero.strength, hero.agility, hero.intelligence = 2, 22, 13, 17
    by_level = unitsdoo.Unit(b"YYU\0", 0, 0.0, 0.0, 0.0, 0.0, scale, b"YYU\0", 2, 12, random_flag=0,
                             random_data=bytes([3, 0, 0, 1]))
    from_group = unitsdoo.Unit(b"YYU\0", 0, 1.0, 1.0, 0.0, 0.0, scale, b"YYU\0", 2, 12, random_flag=1,
                               random_data=struct.pack("<ii", 2, 1))
    custom = unitsdoo.Unit(b"YYU\0", 0, 2.0, 2.0, 0.0, 0.0, scale, b"YYU\0", 2, 12, random_flag=2,
                           random_units=[(b"hfoo", 50), (b"hkni", 50)])
    odd = unitsdoo.Unit(b"ngol", 0, 3.0, 3.0, 0.0, 0.0, scale, b"ngol", 2, 27, gold=15000, random_flag=641)
    return unitsdoo.UnitFile(version, subversion, [start, hero, by_level, from_group, custom, odd])


@pytest.mark.parametrize("version, subversion", sorted(doo.VERSIONS))
def test_doodads_roundtrip(version, subversion):
    df = _doodads(version, subversion)
    assert doo.parse(doo.serialize(df)) == df


@pytest.mark.parametrize("version, subversion", sorted(unitsdoo.VERSIONS))
def test_units_roundtrip(version, subversion):
    uf = _units(version, subversion)
    assert unitsdoo.parse(unitsdoo.serialize(uf)) == uf


def test_fields_the_version_cannot_store_are_refused():
    df = _doodads(8, 11)
    df.doodads[0].entries = [bytes(36)]
    with pytest.raises(FormatError):
        doo.serialize(df)
    uf = _units(8, 9)
    uf.units[1].strength = 1
    with pytest.raises(FormatError):
        unitsdoo.serialize(uf)
    uf = _units(8, 11)
    uf.units[2].random_data = b"\0"
    with pytest.raises(FormatError):
        unitsdoo.serialize(uf)


def test_unit_tail_entries_are_unsupported():
    data = bytearray(unitsdoo.serialize(_units(13, 11)))
    data[-4:] = (1).to_bytes(4, "little")
    with pytest.raises(FormatError):
        unitsdoo.parse(bytes(data))


@pytest.mark.parametrize("module, model", [(doo, _doodads(13, 11)), (unitsdoo, _units(12, 9))])
def test_bad_magic_version_truncation_and_trailing_data_raise(module, model):
    data = module.serialize(model)
    for bad in (b"XXdo" + data[4:], data[:4] + (9).to_bytes(4, "little") + data[8:], data[:-3], data + b"\0"):
        with pytest.raises(FormatError):
            module.parse(bad)


@pytest.mark.parametrize("name, codec", [("war3map.doo", doo), ("war3mapUnits.doo", unitsdoo)])
@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_roundtrip_is_byte_exact(map_id, name, codec):
    data = open_sample(map_id).read(name)
    if data is None:
        pytest.skip(f"no {name}")
    model = codec.parse(data)
    assert (model.version, model.subversion) in codec.VERSIONS
    assert codec.serialize(model) == data
