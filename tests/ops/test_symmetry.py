import pytest

from corpus import HAVE_INSTALL, _storage
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.newmap import new_map
from wc3mcp.ops.placed import placed_edit, placed_list
from wc3mcp.ops.symmetry import reflect, reflect_rect, turn
from wc3mcp.ops.terrain import terrain_edit, terrain_get

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance="Custom_V1")


@pytest.fixture
def half_built(tmp_path, catalog):
    """A map with a hill and two objects in its west half, ready to be mirrored east."""
    project = new_map(str(tmp_path / "Mirror.w3x"), catalog, width=96, height=96, tileset="L", players=2,
                      fill_tile="Lgrs")
    terrain_edit(project, catalog, [
        {"op": "plateau", "x": -2000, "y": 1000, "radius": 600, "height": 384},
        {"op": "paint", "tile": "Lrok", "x": -2000, "y": 1000, "radius": 600}])
    placed_edit(project, catalog, [
        {"op": "add", "kind": "unit", "type": "hfoo", "x": -2000, "y": 1000, "owner": 0, "angle": 30},
        {"op": "add", "kind": "destructible", "type": "LTlt", "x": -1500, "y": -1500, "angle": 0}])
    return project, catalog


def height_at(project, x, y):
    return terrain_get(project, [x - 1, y - 1, x + 1, y + 1], ["height"], 1)["layers"]["height"][0][0]


def tile_at(project, x, y):
    return terrain_get(project, [x - 1, y - 1, x + 1, y + 1], ["texture"], 1)["layers"]["texture"][0][0]


def test_reflect_and_turn_follow_the_axis():
    assert reflect("x", (0, 0), 100, 50) == (-100, 50)
    assert reflect("y", (0, 0), 100, 50) == (100, -50)
    assert reflect("point", (0, 0), 100, 50) == (-100, -50)
    assert reflect("rot90", (0, 0), 100, 0) == (0, 100)
    assert (turn("x", 30), turn("y", 30), turn("point", 30), turn("rot90", 30)) == (150, 330, 210, 120)
    assert reflect_rect("x", (0, 0), (-3000, -1000, -1000, 1000)) == (1000, -1000, 3000, 1000)


def test_terrain_mirrors_height_and_tiles_across_the_axis(half_built):
    project, catalog = half_built
    assert height_at(project, 2000, 1000) == 0
    terrain_edit(project, catalog, [{"op": "mirror", "axis": "x"}])
    assert height_at(project, 2000, 1000) == height_at(project, -2000, 1000) > 300
    assert tile_at(project, 2000, 1000) == tile_at(project, -2000, 1000) == "Lrok"
    terrain_edit(project, catalog, [{"op": "mirror", "axis": "x", "from": [0, -6144, 6144, 6144]}])
    assert height_at(project, -2000, 1000) > 300      # mirroring back gives the same map


def test_placed_objects_mirror_with_their_facing_and_can_change_owner(half_built):
    project, catalog = half_built
    result = placed_edit(project, catalog, [
        {"op": "mirror", "axis": "x", "owner_map": {"0": 1}}])
    assert any("2 object(s) mirrored (x)" in note for note in result["layout"])
    units = placed_list(project, catalog, kind="unit", limit=500)["items"]
    east = [u for u in units if u["x"] > 0]
    assert len(east) == 1 and round(east[0]["x"]) == 2000 and round(east[0]["y"]) == 1000
    assert east[0]["owner"] == 1 and round(east[0]["angle"]) == 150        # 180 - 30
    trees = placed_list(project, catalog, kind="destructible", limit=500)["items"]
    assert sorted(round(t["x"]) for t in trees) == [-1500, 1500]


def test_a_second_mirror_replaces_the_copies_instead_of_stacking_them(half_built):
    project, catalog = half_built
    placed_edit(project, catalog, [{"op": "mirror", "axis": "x"}])
    placed_edit(project, catalog, [{"op": "mirror", "axis": "x"}])
    units = placed_list(project, catalog, kind="unit", limit=500)["items"]
    assert len([u for u in units if u["x"] > 0]) == 1                     # replace=true cleared the first copy
    placed_edit(project, catalog, [{"op": "mirror", "axis": "x", "replace": False}])
    units = placed_list(project, catalog, kind="unit", limit=500)["items"]
    assert len([u for u in units if u["x"] > 0]) == 2


def test_mirror_refuses_what_it_cannot_do(half_built):
    project, catalog = half_built
    for op, code in (({"op": "mirror", "axis": "sideways"}, "bad_value"),
                     ({"op": "mirror", "axis": "rot90", "from": [-3000, -500, -1000, 500]}, "bad_value"),
                     ({"op": "mirror", "axis": "x", "from": [0, 0]}, "bad_value"),
                     ({"op": "mirror", "axis": "x", "kinds": ["region"]}, "bad_value"),
                     ({"op": "mirror", "axis": "x", "owner_map": {"0": "blue"}}, "bad_value")):
        with pytest.raises(ToolError) as e:
            placed_edit(project, catalog, [op])
        assert e.value.code == code, op
    with pytest.raises(ToolError) as e:
        terrain_edit(project, catalog, [{"op": "mirror", "axis": "rot90", "from": [-3000, -500, -1000, 500]}])
    assert e.value.code == "bad_value" and "square" in e.value.message
