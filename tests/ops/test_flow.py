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
