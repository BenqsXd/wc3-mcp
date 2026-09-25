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
        {"op": "add", "kind": "unit", "type": "uDNR", "x": 64, "y": 64, "owner": 24, "random": {"level": 4}}],
        verbose=True)
    assert result["changed"] and set(result["files"]) == {"war3mapUnits.doo", "war3map.doo"}
    assert len(result["created"]) == result["created_count"] == 6 and len(result["warnings"]) == 4
    assert result["warnings"][0].startswith("doodad LRrk: scale 1/1/2 is outside its range")
    assert "belongs to player 5, which war3map.w3i does not list" in result["warnings"][1]
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


def test_rows_add_many_and_created_is_a_range(melee, catalog):
    result = placed_edit(melee, catalog, [
        {"op": "add", "kind": "destructible", "life": 80, "columns": ["type", "x", "y", "variation", "angle"],
         "rows": [["LTlt", -512, 512, 2, 113], ["LTlt", -256, 512, 3, 20], ["ATtr", 0, 512, 1, 0]]},
        {"op": "add", "kind": "unit", "type": "hfoo", "x": 0, "y": 0}])
    first = int(result["created"][0].split(":")[1].split("..")[0])
    assert result["created"] == [f"destructible:{first}..{first + 2}", f"unit:{result['created'][1].split(':')[1]}"]
    assert result["created_count"] == 4
    trees = {x["ref"]: x for x in placed_list(melee, catalog, kind="destructible", limit=5000)["items"]}
    # LTlt has bfxr 270: the editor (and placed_edit since 1.4) forces that angle whatever the row asked for
    assert (trees[f"destructible:{first}"]["variation"], trees[f"destructible:{first}"]["angle"],
            trees[f"destructible:{first + 2}"]["type"], trees[f"destructible:{first + 1}"]["life"]) == (2, 270.0, "ATtr", 80)
    err = _error(placed_edit, melee, catalog, [{"op": "add", "kind": "doodad", "columns": ["type", "x"],
                                                "rows": [["LTlt", 0, 0]]}])
    assert err.code == "bad_value" and err.details["path"] == "ops[0].rows[0]"


def test_scatter_places_weighted_types_away_from_exclusions(melee, catalog):
    ops = [{"op": "scatter", "kind": "destructible", "types": {"LTlt": 3, "ATtr": 1}, "count": 60,
            "rect": [-1536, -1536, 1536, 1536], "exclude": [{"x": 0, "y": 0, "radius": 600},
                                                            {"rect": [-1536, -1536, -1000, 1536]}],
            "min_distance": 128, "seed": 5, "life": 90}]
    before = {x["ref"] for x in placed_list(melee, catalog, kind="destructible", limit=5000)["items"]}
    result = placed_edit(melee, catalog, ops, verbose=True)
    assert result["created_count"] == 60 and len(result["created"]) == 60
    new = [x for x in placed_list(melee, catalog, kind="destructible", limit=5000)["items"] if x["ref"] not in before]
    assert len(new) == 60 and {x["type"] for x in new} == {"LTlt", "ATtr"} and {x["life"] for x in new} == {90}
    for a in new:
        assert -1000 < a["x"] <= 1536 and -1536 <= a["y"] <= 1536 and a["x"] ** 2 + a["y"] ** 2 > 600 ** 2
        assert all((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 >= 127.9 ** 2 for b in new if b is not a)
        assert a["angle"] == 270.0   # trees stand at their fixed rotation
    assert len({x["variation"] for x in new if x["type"] == "LTlt"}) > 1
    melee.close(discard=True)
    again = MapProject.open(melee.source)
    placed_edit(again, catalog, ops)
    assert [(x["x"], x["y"], x["type"]) for x in placed_list(again, catalog, kind="destructible", limit=5000)["items"]
            if x["ref"] not in before] == [(x["x"], x["y"], x["type"]) for x in new]   # a seed repeats the layout
    err = _error(placed_edit, again, catalog, [{"op": "scatter", "kind": "doodad", "types": ["LPgp"], "count": 5}])
    assert err.code == "bad_value" and "no model" in err.message
    crowded = placed_edit(again, catalog, [{"op": "scatter", "kind": "doodad", "types": ["APms"], "count": 50,
                                            "x": 0, "y": 0, "radius": 200, "min_distance": 150, "seed": 1}])
    assert crowded["created_count"] < 50 and any("placed" in w and "of 50" in w for w in crowded["warnings"])


def test_moving_a_start_location_moves_the_player_start(melee, catalog):
    from wc3mcp.ops.info import info_get

    start = placed_list(melee, catalog, kind="start_location")["items"][0]
    result = placed_edit(melee, catalog, [{"op": "move", "ref": start["ref"], "x": 128, "y": -256}])
    index = next(i for i, p in enumerate(info_get(melee)["players"]) if p["id"] == start["owner"])
    assert result["synced"] == [f"players[{index}].start"] and "war3map.w3i" in result["files"]
    assert info_get(melee)["players"][index]["start"] == [128, -256]


def test_adding_a_doodad_without_a_model_warns(melee, catalog):
    result = placed_edit(melee, catalog, [{"op": "add", "kind": "doodad", "type": "LPgp", "x": 0, "y": 0}])
    assert any("LPgp" in w and "renders nothing" in w for w in result["warnings"])


def test_scales_outside_the_type_range_warn(melee, catalog):
    fine = placed_edit(melee, catalog, [{"op": "add", "kind": "doodad", "type": "ZPsh", "x": 0, "y": 0, "scale": 1.1,
                                         "variation": 1}])
    assert not any("scale" in w or "ZPsh" in w for w in fine["warnings"])
    big = placed_edit(melee, catalog, [{"op": "add", "kind": "doodad", "type": "ZPsh", "x": 0, "y": 0, "scale": 1.55,
                                        "variation": 3} for _ in range(2)])
    scale = [w for w in big["warnings"] if "scale" in w]
    assert len(scale) == 1 and "outside its range 0.8..1.2 (dmis..dmas)" in scale[0] and "clamps" in scale[0]
    assert any("variation 3" in w and "Ruins_Shrub3.mdl" in w for w in big["warnings"])


def test_types_with_a_fixed_rotation_stand_at_it(tmp_path, catalog):
    import math

    from wc3mcp.ops import pathing
    from wc3mcp.ops.newmap import new_map
    from wc3mcp.ops.placed import _Map

    p = new_map(str(tmp_path / "G.w3x"), catalog, width=64, height=64, tileset="D", players=2, fill_tile="Ddrt")
    result = placed_edit(p, catalog, [
        {"op": "add", "kind": "destructible", "type": "DTg3", "x": 0, "y": 0, "angle": 270},
        {"op": "add", "kind": "destructible", "type": "DTg1", "x": 512, "y": 0}])
    angles = {o["type"]: o["angle"] for o in placed_list(p, catalog, kind="destructible")["items"]}
    assert angles == {"DTg3": 0, "DTg1": 270}
    assert sum("fixed rotation" in w for w in result["warnings"]) == 1

    terrain = _Map(p, catalog).terrain
    stored_wrong = pathing.cells(p, terrain, catalog, [("destructible", "DTg3", 0.0, 0.0, math.radians(270))])[0]
    stored_right = pathing.cells(p, terrain, catalog, [("destructible", "DTg3", 0.0, 0.0, 0.0)])[0]
    assert stored_wrong == stored_right


def test_setting_a_waygate_explains_how_units_use_it(tmp_path, catalog):
    from wc3mcp.ops.newmap import new_map
    from wc3mcp.ops.script import script_build

    p = new_map(str(tmp_path / "W.w3x"), catalog, width=64, height=64, players=2)
    elements_edit(p, catalog, "region", [{"op": "upsert", "name": "Out", "left": 1024, "bottom": 1024, "right": 1280,
                                          "top": 1280}])
    out = placed_edit(p, catalog, [{"op": "add", "kind": "unit", "type": "nwgt", "x": 0, "y": 0, "owner": 27,
                                    "waygate": "Out"}])
    assert any("smart" in w for w in out["warnings"])
    script_build(p, catalog)
    text = p.read("war3map.j").decode("utf-8")
    assert "call WaygateActivate(" in text and "call WaygateSetDestination(" in text


def test_placed_list_filters_by_one_type_or_several(melee, catalog):
    units = placed_list(melee, catalog, kind="unit", limit=5000)["items"]
    first, second = sorted({u["type"] for u in units})[:2]
    one = placed_list(melee, catalog, kind="unit", type_id=first, limit=5000)
    both = placed_list(melee, catalog, kind="unit", type_id=[first, second], limit=5000)
    assert {u["type"] for u in one["items"]} == {first}
    assert {u["type"] for u in both["items"]} == {first, second} and both["total"] > one["total"]


def test_an_area_delete_clears_a_generators_ground_and_can_run_twice(melee, catalog):
    placed_edit(melee, catalog, [{"op": "add", "kind": "destructible", "type": "LTlt", "x": x, "y": 0}
                                 for x in (-3000, -2900, -2800)])
    clear = [{"op": "delete", "kind": "destructible", "area": [-3050, -50, -2850, 50], "types": ["LTlt"]}]
    assert placed_edit(melee, catalog, clear)["deleted"] == 2
    assert "deleted" not in placed_edit(melee, catalog, clear)
    assert placed_edit(melee, catalog, [{"op": "delete", "ref": "unit:99999", "missing_ok": True}])["skipped"] == [
        "unit:99999"]
