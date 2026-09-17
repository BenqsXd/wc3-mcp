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


def test_command_card_pitfalls_are_warnings(catalog):
    from wc3mcp.formats import objmods

    def entry(base, new, **values):
        mods = [objmods.Mod(k.encode(), objmods.INT if isinstance(v, int) else objmods.STRING, v)
                for k, v in values.items()]
        return objmods.ObjectEntry(base.encode(), new.encode(), mods)

    units = objmods.ObjectMods(3, False)
    units.custom = [entry("htow", "h001", utra="h002"), entry("hfoo", "h002", ubpx=3, ubpy=1),
                    entry("ewsp", "e000", uabi="Awha"), entry("otau", "o000", uhpm=900),
                    entry("ewsp", "e001", uabi="Awha", ubui="")]
    result = validate({"war3map.w3u": objmods.serialize(units)}, catalog)
    found = {(w["check"], w["message"].split(":")[0]) for w in result["warnings"]}
    assert ("command_card", "unit h001") in found and ("inherited_builds", "unit e000") in found
    assert ("inherited_builds", "unit e001") not in found
    locked = [w["message"] for w in result["warnings"] if w["check"] == "locked_ability"]
    research = next(m.split()[1] for m in locked if "o000 (" in m)   # a Tauren ability's research (data-set dependent)
    clash = next(w["message"] for w in result["warnings"] if w["check"] == "command_card")
    assert clash.startswith("unit h001: h002, Rally share button position (3, 1)")
    assert not [w for w in result["warnings"] if w["check"] == "command_card" and "unit h00" not in w["message"]]
    scripted = validate({"war3map.w3u": objmods.serialize(units),
                         "war3map.j": f"call SetPlayerTechResearched(Player(0), '{research}', 1)".encode()}, catalog)
    assert not [w for w in scripted["warnings"] if w["check"] == "locked_ability" and research in w["message"]]
