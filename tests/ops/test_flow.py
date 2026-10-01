import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.flow import flow_report, melee_check
from wc3mcp.ops.newmap import new_map
from wc3mcp.ops.placed import placed_edit
from wc3mcp.project.workspace import MapProject

pytestmark = pytest.mark.skipif(not HAVE_INSTALL or not ladder_maps(),
                                reason="needs the Warcraft III install and a melee map")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance="Custom_V1")


@pytest.fixture
def ladder(tmp_path):
    src = tmp_path / ladder_maps()[0].name
    src.write_bytes(ladder_maps()[0].read_bytes())
    return MapProject.open(src)


def test_flow_measures_walking_distances_chokes_and_what_is_cut_off(ladder, catalog):
    doc = flow_report(ladder, catalog)
    assert doc["gold_mines"] > 0 and doc["walkable_corners"] > 1000
    starts = doc["starts"]
    assert len(starts) >= 2
    for row in starts.values():
        assert row["own_mine_distance"] is not None and row["own_mine_distance"] < 1600
        assert row["walkable_within_1500"] > 50           # a base needs room around it
        assert row["reaches"] > 500
    [pair] = doc["start_pairs"][:1]
    assert pair["distance"] > 1000 and pair["choke"] > 0   # the two starts are connected on foot
    assert len(pair["choke_at"]) == 2
    for pocket in doc["pockets"]:                          # a pocket sits somewhere on the map, in world units
        x, y = pocket["at"]
        assert abs(x) <= 8192 and abs(y) <= 8192 and pocket["corners"] > 0
    assert 0 < doc["reachable_share"] <= 1


def test_flow_sees_a_start_walled_off_by_trees(tmp_path, catalog):
    project = new_map(str(tmp_path / "Walled.w3x"), catalog, width=96, height=96, tileset="L", players=2,
                      fill_tile="Lgrs")
    open_map = flow_report(project, catalog)
    assert all(p["distance"] is not None for p in open_map["start_pairs"])
    first = open_map["starts"][sorted(open_map["starts"])[0]]
    x, y = first["at"]
    placed_edit(project, catalog, [
        {"op": "add", "kind": "destructible", "columns": ["type", "x", "y"],
         "rows": [["LTlt", x + dx * 64, y + dy * 64] for dx in range(-14, 15) for dy in range(-14, 15)
                  if max(abs(dx), abs(dy)) in (13, 14)]}])
    walled = flow_report(project, catalog)
    assert walled["start_pairs"][0]["distance"] is None     # the ring closed the way
    walled_start = walled["starts"][sorted(walled["starts"])[0]]
    assert walled_start["reaches"] < first["reaches"] / 10  # it only reaches the inside of its own ring now


def test_melee_check_measures_a_shipped_map_against_its_own_kind(ladder, catalog):
    doc = melee_check(ladder, catalog, sample=6)
    assert doc["players"] >= 2 and doc["norms"]["maps"] >= 1
    metrics = doc["metrics"]
    for key in ("mines_per_player", "start_distance", "own_mine_distance", "creeps_per_player",
                "playable_per_player", "tiles", "doodad_density"):
        assert key in metrics and "value" in metrics[key]
    graded = [m for m in metrics.values() if "verdict" in m]
    assert graded and sum(1 for m in graded if m["verdict"] == "inside") >= len(graded) // 2
    assert "shipped with this install" in doc["norms"]["source"]


def test_melee_check_marks_an_empty_map_as_unlike_the_shipped_ones(tmp_path, catalog):
    project = new_map(str(tmp_path / "Empty.w3x"), catalog, width=32, height=32, tileset="L", players=2)
    doc = melee_check(project, catalog, sample=6)
    verdicts = {key: m.get("verdict") for key, m in doc["metrics"].items()}
    assert verdicts["mines_per_player"] == "below" and verdicts["creeps_per_player"] == "below"
    assert verdicts["playable_per_player"] == "below"
    single = new_map(str(tmp_path / "Solo.w3x"), catalog, width=32, height=32, tileset="L", players=1)
    with pytest.raises(ToolError) as e:
        melee_check(single, catalog, sample=2)
    assert e.value.code == "bad_value" and "two start locations" in e.value.message


def test_areas_label_the_ground_a_unit_can_walk_between(tmp_path):
    from corpus import _storage
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops.flow import areas
    from wc3mcp.ops.newmap import new_map
    from wc3mcp.ops.terrain import terrain_edit

    catalog = Catalog(_storage(), balance="Custom_V1")
    p = new_map(str(tmp_path / "A.w3x"), catalog, width=64, height=64, tileset="L", players=2, fill_tile="Lgrs")
    terrain_edit(p, catalog, [{"op": "cliff", "rect": [-4096, -256, 4096, 256], "level": 6}])   # a wall across
    doc = areas(p, catalog, grid_step=8)
    # south of the wall, north of it, and the wall's own flat top (a plateau is ground too)
    assert doc["count"] == 3 and doc["areas"][0]["cells"] > 1000
    south, top, north = sorted(doc["areas"], key=lambda a: a["sample"][1])
    assert south["rect"][3] < top["rect"][1] and top["rect"][3] < north["rect"][1]
    labels = {v for row in doc["grid"]["rows"] for v, _ in row}
    assert labels == {0, 1, 2, 3}


def test_sight_is_blocked_by_higher_cliffs_one_way_and_by_trees_not_barrels(tmp_path, catalog):
    from wc3mcp.ops.flow import sight
    from wc3mcp.ops.terrain import terrain_edit

    p = new_map(str(tmp_path / "S.w3x"), catalog, width=64, height=64, tileset="L", players=2, fill_tile="Lgrs")
    terrain_edit(p, catalog, [{"op": "cliff", "rect": [-4096, 1024, 4096, 4096], "level": 3}])   # high ground north
    doc = sight(p, catalog, [0, -1024, 0, -256])
    assert doc["sight"]["visible"] and doc["sight"]["visible_back"]
    up = sight(p, catalog, [[0, -512], [0, 1536]])["sight"]
    assert up["from_level"] < up["to_level"]
    assert not up["visible"] and up["blocked_by"]["kind"] == "cliff"
    assert 700 < up["blocked_by"]["at"][1] < 1200         # where the cliff rises
    assert up["visible_back"]                             # the high ground looks down
    placed_edit(p, catalog, [{"op": "add", "kind": "destructible", "columns": ["type", "x", "y"],
                              "rows": [["LTlt", 0, -640], ["LTbr", 512, -640]]}])
    tree = sight(p, catalog, [0, -1024, 0, -256])["sight"]
    assert not tree["visible"] and tree["blocked_by"]["type"] == "LTlt" and tree["blocked_by"]["at"] == [0, -640]
    assert sight(p, catalog, [512, -1024, 512, -256])["sight"]["visible"]      # a barrel hides nothing
    assert sight(p, catalog, [0, -1024, 0, -640 + 40])["sight"]["visible"]     # a unit against the tree is seen
    with pytest.raises(ToolError):
        sight(p, catalog, [0, 1, 2])


def test_open_near_lists_open_ground_in_sight_on_the_same_level(tmp_path, catalog):
    from wc3mcp.ops.flow import sight
    from wc3mcp.ops.terrain import terrain_edit

    p = new_map(str(tmp_path / "O.w3x"), catalog, width=64, height=64, tileset="L", players=2, fill_tile="Lgrs")
    terrain_edit(p, catalog, [{"op": "cliff", "rect": [-4096, 512, 4096, 4096], "level": 3}])
    placed_edit(p, catalog, [{"op": "add", "kind": "destructible", "columns": ["type", "x", "y"],
                              "rows": [["LTlt", x, -384] for x in range(-1024, 1025, 128)]}])   # a tree line south
    doc = sight(p, catalog, open_near=[0, 0, 900, 5])["open_near"]
    assert doc["found"] > 20 and len(doc["spots"]) == 5
    assert [s["distance"] for s in doc["spots"]] == sorted(s["distance"] for s in doc["spots"])
    for s in doc["spots"]:
        x, y = s["at"]
        assert -384 + 128 <= y < 512 and s["walk"] >= s["distance"] - 64   # not on the cliff, not by or past the trees
    everything = sight(p, catalog, open_near=[0, 0, 900, 500])["open_near"]["spots"]
    assert all(s["at"][1] < 512 for s in everything)                    # nothing on the high ground
    assert all(-384 + 128 <= s["at"][1] < 512 or abs(s["at"][0]) > 1024 for s in everything)


def test_a_custom_units_pathing_texture_blocks_the_ground_it_stands_on(tmp_path, catalog):
    """A shop copied from the Goblin Merchant has a custom id the stock data does not know: its footprint comes
    from the map's own object data."""
    from wc3mcp.ops.flow import _grid
    from wc3mcp.ops.objdata import objdata_edit
    from wc3mcp.ops.pathing import cells, map_value

    project = new_map(str(tmp_path / "Shop.w3x"), catalog, width=32, height=32, tileset="L", players=2)
    objdata_edit(project, catalog, "unit", [{"op": "create", "base": "ngme", "id": "n0SH", "set": {"Name": "Vendor"}}])
    placed_edit(project, catalog, [{"op": "add", "kind": "unit", "type": "n0SH", "x": 0, "y": 0, "owner": 15}])
    scene, _, blockers, _ = _grid(project, catalog, corners=False)
    stock, width, _, _ = cells(project, scene.terrain, catalog, blockers)
    own, _, _, _ = cells(project, scene.terrain, catalog, blockers, map_value(project, catalog))
    assert sum(stock) - sum(own) >= 16   # the merchant's footprint is at least 4x4 cells: blocked only when known
