import pytest

from corpus import HAVE_INSTALL, _storage, open_sample, sample_map_ids
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.validate import validate

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs game data from the install")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)


def map_files(arc) -> dict:
    return {n: arc.read(n) for n in arc.list()
            if ("\\" not in n and n.lower().startswith("war3map")) or n.lower().startswith("scripts\\")}


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_shipped_maps_have_no_errors(map_id, catalog):
    arc = open_sample(map_id)
    result = validate(map_files(arc), catalog, has_file=lambda name: arc.find(name) is not None)
    assert result["errors"] == []


def test_broken_references_are_errors(catalog):
    arc = open_sample(sample_map_ids()[0])
    files = map_files(arc)
    files.pop("war3map.j", None)
    files.pop("war3map.lua", None)
    result = validate(files, catalog, has_file=lambda name: False)
    assert any(e["check"] == "script_language" for e in result["errors"])


def test_placed_objects_without_models_and_moved_starts_are_warnings(catalog):
    from wc3mcp.formats import doo, unitsdoo, w3i

    arc = open_sample(sample_map_ids()[0])
    files = map_files(arc)
    units = unitsdoo.parse(files["war3mapUnits.doo"])
    start = next(u for u in units.units if u.id == b"sloc")
    start.x += 512
    files["war3mapUnits.doo"] = unitsdoo.serialize(units)
    doodads = doo.parse(files["war3map.doo"]) if "war3map.doo" in files else doo.DoodadFile(8, 11)
    grass = doo.Doodad(b"LPgp", 0, 0.0, 0.0, 0.0, 0.0, [1.0, 1.0, 1.0], b"LPgp", 2, 255)
    doodads.doodads += [grass, grass]
    files["war3map.doo"] = doo.serialize(doodads)
    result = validate(files, catalog, has_file=lambda name: arc.find(name) is not None)
    models = [w["message"] for w in result["warnings"] if w["check"] == "model"]
    assert any(m.startswith("2 placed doodad(s) LPgp: ") and "GrassPatch.mdl" in m for m in models)
    starts = [w["message"] for w in result["warnings"] if w["check"] == "start_location"]
    player = next(p for p in w3i.parse(files["war3map.w3i"]).players if p.id == start.owner)
    assert starts == [f"player {start.owner}: the start location marker is at ({start.x:g}, {start.y:g}) but "
                      f"war3map.w3i starts the player at ({player.start_x:g}, {player.start_y:g}); move it with "
                      "placed_edit, which updates both"]
    imported = validate(files, catalog, has_file=lambda name: "grasspatch" in name.lower())
    assert not any("LPgp" in w["message"] for w in imported["warnings"] if w["check"] == "model")


def test_placed_variations_without_a_classic_model_are_warnings(catalog):
    from wc3mcp.formats import doo

    arc = open_sample(sample_map_ids()[0])
    files = map_files(arc)
    doodads = doo.parse(files["war3map.doo"]) if "war3map.doo" in files else doo.DoodadFile(8, 11)
    shrub = [doo.Doodad(b"ZPsh", v, 0.0, 0.0, 0.0, 0.0, [1.0, 1.0, 1.0], b"ZPsh", 2, 255) for v in (0, 3)]
    doodads.doodads += shrub
    files["war3map.doo"] = doo.serialize(doodads)
    models = [w["message"] for w in validate(files, catalog, has_file=lambda name: arc.find(name) is not None)["warnings"]
              if w["check"] == "model" and "ZPsh" in w["message"]]
    assert len(models) == 1 and models[0].startswith("1 placed doodad(s) ZPsh: ") and "Ruins_Shrub3.mdl" in models[0]
