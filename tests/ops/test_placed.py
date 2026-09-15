import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps, open_sample
from wc3mcp.errors import ToolError
from wc3mcp.formats import doo, unitsdoo, w3e
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.elements import elements_edit
from wc3mcp.ops.placed import placed_edit, placed_list
from wc3mcp.ops.triggers import triggers_edit
from wc3mcp.project.workspace import MapProject

HUMAN01 = "casc:Campaign/Reforged/ROC/Human01.w3x"
pytestmark = pytest.mark.skipif(not HAVE_INSTALL or not ladder_maps(),
                                reason="needs the Warcraft III install and ladder maps")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)


def _copy(tmp_path, name: str, data: bytes) -> MapProject:
    src = tmp_path / name
    src.write_bytes(data)
    return MapProject.open(src)


@pytest.fixture
def melee(tmp_path):
    return _copy(tmp_path, ladder_maps()[0].name, ladder_maps()[0].read_bytes())


def _error(fn, *args) -> ToolError:
    with pytest.raises(ToolError) as e:
        fn(*args)
    return e.value


def _files(project) -> tuple:
    return project.read("war3mapUnits.doo"), project.read("war3map.doo")


def test_list_filters_and_pages(tmp_path, catalog):
    project = _copy(tmp_path, "Human01.w3x", open_sample(HUMAN01).data)
    everything = placed_list(project, catalog, limit=5000)
    units = unitsdoo.parse(project.read("war3mapUnits.doo")).units
    doodads = doo.parse(project.read("war3map.doo")).doodads
    assert everything["total"] == len(units) + len(doodads) == len(everything["items"])
    left, bottom, right, top = everything["bounds"]["playable"]
    assert left < right and bottom < top
    kinds = {x["kind"] for x in everything["items"]}
    assert {"unit", "start_location", "doodad", "destructible"} <= kinds

    footmen = placed_list(project, catalog, kind="unit", type_id="hfoo")
    assert footmen["total"] > 0 and all(x["type"] == "hfoo" and x["name"] == "Footman" for x in footmen["items"])
    unit = footmen["items"][0]
    assert unit["ref"] == f"unit:{int(unit['script_name'][-4:])}" and unit["script_name"].startswith("gg_unit_hfoo_")
    owned = placed_list(project, catalog, owner=unit["owner"])
    assert owned["total"] and all(x["owner"] == unit["owner"] for x in owned["items"])
    box = [unit["x"] - 1, unit["y"] - 1, unit["x"] + 1, unit["y"] + 1]
    assert unit["ref"] in [x["ref"] for x in placed_list(project, catalog, area=box)["items"]]
    page = placed_list(project, catalog, kind="destructible", limit=10, offset=5)
    assert len(page["items"]) == 10 and page["items"][0] == placed_list(project, catalog, kind="destructible",
                                                                        limit=6)["items"][5]
    assert _error(placed_list, project, catalog, "region").code == "bad_kind"


def test_add_set_move_delete_round_trip(melee, catalog):
    before = _files(melee)
    result = placed_edit(melee, catalog, [
        {"op": "add", "kind": "unit", "type": "Hpal", "x": 128, "y": -256, "owner": 2, "angle": 90,
         "hero": {"level": 3, "strength": 25}, "inventory": [{"slot": 1, "item": "ratc"}],
         "abilities": [{"id": "AHhb", "level": 1}], "life": 50, "mana": 100,
         "drops": {"sets": [[{"item": "ratc", "chance": 60}, {"item": "YiI1", "chance": 40}]]}},
        {"op": "add", "kind": "item", "type": "ratc", "x": 0, "y": 0},
        {"op": "add", "kind": "destructible", "type": "LTlt", "x": 512, "y": 512, "life": 40},
        {"op": "add", "kind": "doodad", "type": "LRrk", "x": -512, "y": 512, "scale": [1, 1, 2], "z": 300},
        {"op": "add", "kind": "start_location", "x": 256, "y": 256, "owner": 5},
        {"op": "add", "kind": "unit", "type": "uDNR", "x": 64, "y": 64, "owner": 24, "random": {"level": 4}}])
    assert result["changed"] and set(result["files"]) == {"war3mapUnits.doo", "war3map.doo"}
    assert len(result["created"]) == 6 and len(result["warnings"]) == 2
    items = {x["ref"]: x for x in placed_list(melee, catalog, limit=5000)["items"]}
    hero, item, tree, rock, start, creep = (items[r] for r in result["created"])
    terrain = w3e.parse(melee.read("war3map.w3e"))
    assert hero["z"] == pytest.approx(w3e.ground_height(terrain, 128, -256), abs=1e-3)
    assert (hero["type"], hero["owner"], hero["angle"], hero["life"], hero["mana"], hero["gold"]) == (
        "Hpal", 2, 90.0, 50, 100, 12500)
    assert hero["hero"] == {"level": 3, "strength": 25, "agility": 0, "intelligence": 0}
    assert hero["inventory"] == [{"slot": 1, "item": "ratc"}]
    assert hero["abilities"] == [{"id": "AHhb", "autocast": False, "level": 1}]
    assert hero["drops"] == {"table": None, "sets": [[{"item": "ratc", "chance": 60}, {"item": "YiI1", "chance": 40}]]}
    assert (item["kind"], item["angle"], "owner" in item) == ("item", 270.0, False)
    assert (tree["kind"], tree["life"], tree["flags"]) == ("destructible", 40, 2)
    assert (rock["kind"], rock["z"], rock["scale"]) == ("doodad", 300.0, [1.0, 1.0, 2.0])
    assert (start["type"], start["owner"]) == ("sloc", 5)
    assert creep["random"] == {"level": 4, "item_class": 0} and creep["name"] == "Random Unit"
    raw = next(u for u in unitsdoo.parse(melee.read("war3mapUnits.doo")).units if u.id == b"ratc")
    assert (raw.owner, raw.gold, raw.hero_level, raw.random_flag, raw.random_data) == (27, 0, 0, 0, b"\x01\0\0\0")

    placed_edit(melee, catalog, [{"op": "move", "ref": hero["ref"], "x": -128, "y": 128},
                                 {"op": "set", "ref": hero["ref"], "life": None, "type": "Hamg", "drops": None}])
    moved = next(x for x in placed_list(melee, catalog, kind="unit")["items"] if x["ref"] == hero["ref"])
    assert (moved["x"], moved["y"], moved["type"], moved["skin"], moved["life"], moved["drops"]) == (
        -128.0, 128.0, "Hamg", "Hamg", None, None)
    assert moved["z"] == pytest.approx(w3e.ground_height(terrain, -128, 128), abs=1e-3)
    assert not placed_edit(melee, catalog, [{"op": "set", "ref": moved["ref"], "x": -128}])["changed"]

    placed_edit(melee, catalog, [{"op": "delete", "ref": r} for r in result["created"]])
    assert _files(melee) == before


def test_errors_leave_the_map_untouched(melee, catalog):
    before = _files(melee)
    unit = placed_list(melee, catalog, kind="unit", limit=1)["items"][0]
    bad = {
        "bad_value": [
            [{"op": "add", "kind": "unit", "type": "xxxx", "x": 0, "y": 0}],
            [{"op": "add", "kind": "unit", "type": "hfoo", "x": 0}],
            [{"op": "add", "kind": "unit", "type": "hfoo", "x": 0, "y": 0, "owner": 28}],
            [{"op": "add", "kind": "unit", "type": "hfoo", "x": 100000, "y": 0}],
            [{"op": "add", "kind": "item", "type": "hfoo", "x": 0, "y": 0}],
            [{"op": "add", "kind": "start_location", "x": 0, "y": 0}],
            [{"op": "set", "ref": unit["ref"], "inventory": [{"slot": 0, "item": "ratc"}, {"slot": 0, "item": "ratc"}]}],
            [{"op": "set", "ref": unit["ref"], "inventory": [{"slot": 6, "item": "ratc"}]}],
            [{"op": "set", "ref": unit["ref"], "abilities": [{"id": "Zzzz"}]}],
            [{"op": "set", "ref": unit["ref"], "drops": {"table": 99}}],
            [{"op": "set", "ref": unit["ref"], "random": {"level": 1}}],
            [{"op": "set", "ref": unit["ref"], "waygate": "No Such Region"}],
            [{"op": "set", "ref": unit["ref"], "acquisition": "far"}],
            [{"op": "set", "ref": "unit"}],
        ],
        "not_found": [[{"op": "set", "ref": "unit:99999", "owner": 1}], [{"op": "delete", "ref": "doodad:99999"}]],
        "bad_op": [[{"op": "teleport", "ref": unit["ref"]}], [{"op": "set", "ref": unit["ref"], "flags": 1}],
                   [{"op": "move", "ref": unit["ref"], "x": 0}]],
        "bad_kind": [[{"op": "add", "kind": "region", "type": "hfoo", "x": 0, "y": 0}]],
    }
    for code, batches in bad.items():
        for ops in batches:
            assert _error(placed_edit, melee, catalog, ops).code == code, ops
    ok_then_bad = [{"op": "add", "kind": "unit", "type": "hfoo", "x": 0, "y": 0}, {"op": "delete", "ref": "unit:99999"}]
    assert _error(placed_edit, melee, catalog, ok_then_bad).details["op_index"] == 1
    assert _files(melee) == before


def test_references_block_deletes_and_waygates_use_region_names(melee, catalog):
    unit = placed_list(melee, catalog, kind="unit", limit=1)["items"][0]
    triggers_edit(melee, catalog, [{"op": "trigger", "name": "Uses", "script":
                                    f"function InitTrig_Uses takes nothing returns nothing\n"
                                    f"    call KillUnit( {unit['script_name']} )\nendfunction"}])
    err = _error(placed_edit, melee, catalog, [{"op": "delete", "ref": unit["ref"]}])
    assert err.code == "in_use" and err.details["triggers"] == ["Uses"]

    elements_edit(melee, catalog, "region", [{"op": "upsert", "name": "Exit", "left": 0, "bottom": 0, "right": 64,
                                              "top": 64}])
    placed_edit(melee, catalog, [{"op": "add", "kind": "unit", "type": "nwgt", "x": 0, "y": 0, "owner": 27,
                                  "waygate": "Exit"}])
    gate = placed_list(melee, catalog, type_id="nwgt")["items"][-1]
    assert gate["waygate"] == "Exit"
    assert _error(elements_edit, melee, catalog, "region", [{"op": "delete", "name": "Exit"}]).code == "in_use"


def test_campaign_map_edit_keeps_other_objects(tmp_path, catalog):
    project = _copy(tmp_path, "Human01.w3x", open_sample(HUMAN01).data)
    before = unitsdoo.parse(project.read("war3mapUnits.doo"))
    doodads = project.read("war3map.doo")
    unit = placed_list(project, catalog, kind="unit", limit=1)["items"][0]
    placed_edit(project, catalog, [{"op": "set", "ref": unit["ref"], "owner": 3, "color": 5}])
    after = unitsdoo.parse(project.read("war3mapUnits.doo"))
    changed = [i for i, (a, b) in enumerate(zip(before.units, after.units)) if a != b]
    assert len(changed) == 1 and (after.units[changed[0]].owner, after.units[changed[0]].color) == (3, 5)
    assert (after.version, after.subversion) == (before.version, before.subversion)
    assert project.read("war3map.doo") == doodads
