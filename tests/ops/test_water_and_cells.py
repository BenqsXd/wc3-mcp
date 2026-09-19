"""Deep water, per-tileset water heights, the river's water level, and the 32-unit cell pathing behind map_flow's
origins/targets."""
import io
import json

import pytest
from PIL import Image

from corpus import HAVE_INSTALL, _storage
from wc3mcp.formats import w3e
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops import flow, pathing, terrain
from wc3mcp.ops.layout import layout_check
from wc3mcp.ops.newmap import new_map
from wc3mcp.ops.placed import placed_edit
from wc3mcp.ops.terrain import terrain_edit, terrain_get

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance="Custom_V1")


def _map(tmp_path, catalog, tileset="L", tile="Lgrs"):
    return new_map(str(tmp_path / "W.w3x"), catalog, width=64, height=64, tileset=tileset, players=2, fill_tile=tile)


def _trench(project, catalog, ground):
    """A full-width trench at y 0 with water at -40: the two starts (north and south of it) on either side."""
    return terrain_edit(project, catalog, [{"op": "plateau", "rect": [-4096, -256, 4096, 256], "height": ground},
                                           {"op": "water", "rect": [-4096, -256, 4096, 256], "level": -40}])


def test_water_level_is_the_drawn_surface_on_every_tileset(tmp_path, catalog):
    for tileset, tile in (("L", "Lgrs"), ("A", "Agrs")):
        project = _map(tmp_path / tileset, catalog, tileset, tile)
        result = _trench(project, catalog, -104)
        assert result["water"][0]["level"] == pytest.approx(-40, abs=0.15)
        assert result["water"][0]["depth"]["min"] == pytest.approx(64, abs=0.2)
        doc = terrain_get(project, [0, 0, 0, 0], ["water"])
        assert doc["layers"]["water"][0][0] == pytest.approx(-40, abs=0.15)
    assert terrain.TILESET_WATER_OFFSET["A"] == -76.8 and terrain.WATER_OFFSET == -89.6


def test_deep_water_cuts_the_map_and_shallow_water_does_not(tmp_path, catalog):
    deep = _map(tmp_path / "deep", catalog)
    result = _trench(deep, catalog, -104)
    assert result["water"][0]["deep_corners"] == result["water"][0]["wet_corners"] > 0
    assert terrain_get(deep, [0, 0, 0, 0], ["pathing"])["layers"]["pathing"][0][0] == "wb"
    assert flow.flow_report(deep, catalog)["start_pairs"][0]["distance"] is None
    assert flow.connect(deep, catalog, ["start:0"], ["start:1"])["sealed"] is True
    shallow = _map(tmp_path / "shallow", catalog)
    result = _trench(shallow, catalog, -80)
    assert result["water"][0]["deep_corners"] == 0
    assert terrain_get(shallow, [0, 0, 0, 0], ["pathing"])["layers"]["pathing"][0][0] == "b"
    assert flow.flow_report(shallow, catalog)["start_pairs"][0]["distance"] is not None
    assert flow.connect(shallow, catalog, ["start:0"], ["start:1"])["sealed"] is False


def test_a_river_takes_a_water_level_joins_standing_water_and_keeps_its_promise(tmp_path, catalog):
    project = _map(tmp_path, catalog)
    first = terrain_edit(project, catalog, [{"op": "river", "path": [[-4000, 0], [4000, 0]], "width": 900,
                                             "water_level": -60, "walkable": False}])["water"][0]
    assert first["water_level"] == pytest.approx(-60, abs=0.15) and first["deep_corners"] > 0
    assert flow.connect(project, catalog, ["start:0"], ["start:1"])["sealed"] is True
    branch = terrain_edit(project, catalog, [{"op": "river", "path": [[1000, 0], [1000, -2000]], "width": 400,
                                              "depth": 120}])["water"][0]
    assert branch["joined"] == pytest.approx(first["water_level"], abs=0.01)
    ford = _map(tmp_path / "ford", catalog)
    wade = terrain_edit(ford, catalog, [{"op": "river", "path": [[-4000, 0], [4000, 0]], "width": 600,
                                         "walkable": True}])["water"][0]
    assert wade["deep_corners"] == 0 and wade["depth"]["max"] <= 40.5
    assert flow.connect(ford, catalog, ["start:0"], ["start:1"])["sealed"] is False


def test_the_cell_grid_finds_the_gap_in_a_tree_wall(tmp_path, catalog):
    project = _map(tmp_path, catalog, "Z", "Zgrs")
    rows = [["ZTtw", x, 1500, 0] for x in list(range(-4096, 0, 128)) + list(range(192, 4097, 128))]
    placed_edit(project, catalog, [{"op": "add", "kind": "destructible", "columns": ["type", "x", "y", "variation"],
                                    "rows": rows}])
    leak = flow.connect(project, catalog, [[0, 500]], [[0, 2500]])
    target = leak["targets"][0]
    assert not leak["sealed"] and target["gap"] == 192 and abs(target["gap_at"][0] - 32) <= 96
    one = placed_edit(project, catalog, [{"op": "add", "kind": "destructible", "type": "ZTtw", "x": 32, "y": 1500}])
    assert flow.connect(project, catalog, [[0, 500]], [[0, 2500]])["targets"][0]["gap"] == 32   # two 1-cell slits
    placed_edit(project, catalog, [{"op": "delete", "ref": one["created"][0]},
                                   {"op": "add", "kind": "destructible", "type": "ZTtw", "x": 0, "y": 1500},
                                   {"op": "add", "kind": "destructible", "type": "ZTtw", "x": 128, "y": 1500}])
    assert flow.connect(project, catalog, [[0, 500]], [[0, 2500]])["sealed"] is True
    with pytest.raises(Exception) as e:
        flow.connect(project, catalog, ["no such region"], [[0, 0]])
    assert e.value.code == "not_found"


def test_footprints_turn_with_the_doodad(catalog):
    t = w3e.Terrain(12, "A", 0, [b"Adrt"], [b"CAdi"], 17, 17, -1024.0, -1024.0, [0x2000] * 289, [0] * 289,
                    [0] * 289, [0] * 289, [2] * 289)
    found = pathing.footprint(catalog, "doodad", "AOla", lambda k, i, f: catalog.field(k, i, f), {})
    if not found or found[0] == found[1] and set(found[2]) == {(found[1] - 1 - y, x) for x, y in found[2]}:
        pytest.skip("AOla has no asymmetric footprint in this build")
    at = {deg: set(pathing.footprint_cells(found, "doodad", 0, 0, deg * 3.14159265 / 180, t))
          for deg in (0, 90, 180, 270)}
    assert at[0] != at[270] and len({frozenset(v) for v in at.values()}) >= 2
    assert set(pathing.footprint_cells(found, "unit", 0, 0, 0.0, t)) == at[270]   # buildings never turn


def test_layout_check_says_why_objects_stand_on_bad_ground(tmp_path, catalog):
    project = _map(tmp_path, catalog)
    _trench(project, catalog, -104)
    placed_edit(project, catalog, [{"op": "add", "kind": "destructible", "type": "LTlt", "x": 0, "y": 0}])
    reasons = layout_check(project, catalog)["ground"]["reasons"]
    assert reasons["destructible"]["deep_water"] == 1


def test_render_area_draws_only_that_part(tmp_path, catalog):
    project = _map(tmp_path, catalog)
    png = terrain.terrain_render(project, catalog, scale=4, area=[-1024, -512, 1024, 512])
    assert Image.open(io.BytesIO(png)).size == (16 * 4, 8 * 4)
    assert terrain.render_area(project, [-1024, -512, 1024, 512]) == {"drawn": [-1024.0, -512.0, 1024.0, 512.0],
                                                                      "tiles": [16, 8]}
    whole = Image.open(io.BytesIO(terrain.terrain_render(project, catalog, scale=1)))
    assert whole.size == (64, 64)


def test_a_fixed_scale_within_rounding_gives_no_warning(tmp_path, catalog):
    project = _map(tmp_path, catalog)
    ok = placed_edit(project, catalog, [{"op": "add", "kind": "doodad", "type": "JScs", "x": 0, "y": 0,
                                         "scale": 1.09}])
    assert not any("scale" in w for w in ok.get("warnings", []))


def test_a_snapshot_restore_keeps_what_was_saved_clean(tmp_path, catalog):
    project = _map(tmp_path, catalog)
    project.save()
    project.snapshot("create", "clean")
    placed_edit(project, catalog, [{"op": "move", "ref": "start_location:0", "x": 0, "y": 0}])
    assert project.status()["dirty"]
    restored = project.snapshot("restore", "clean")
    assert restored["dirty"] == [] and project.status()["dirty"] == []
    json.dumps(restored)


def test_places_on_blocked_ground_walk_from_the_ground_around_them(tmp_path, catalog):
    project = _map(tmp_path, catalog)
    placed_edit(project, catalog, [{"op": "add", "kind": "unit", "type": "ngol", "owner": 27, "x": 0, "y": 1024},
                                   {"op": "add", "kind": "unit", "type": "htow", "owner": 0, "x": 1024, "y": 0}])
    found = flow.connect(project, catalog, [[0, -1500]], [[0, 1024], [1024, 0]])
    assert [t["reachable"] for t in found["targets"]] == [True, True] and not found["sealed"]
    assert not flow.connect(project, catalog, [[0, 1024]], [[0, -1500]])["sealed"]   # from the mine itself
    terrain_edit(project, catalog, [{"op": "plateau", "rect": [-1700, -1700, 1700, 1700], "height": -200},
                                    {"op": "water", "rect": [-1700, -1700, 1700, 1700], "level": -40}])
    with pytest.raises(Exception) as e:   # the middle of a deep lake has nowhere to walk from
        flow.connect(project, catalog, [[0, 0]], [[0, -1500]])
    assert e.value.code == "bad_value"


def test_the_saved_pathing_is_not_trusted_after_doodads_change(tmp_path, catalog):
    project = _map(tmp_path, catalog)
    scene = flow._grid(project, catalog, corners=False)
    assert pathing.cells(project, scene[0].terrain, catalog, scene[2])[3] == "war3map.wpm"
    placed_edit(project, catalog, [{"op": "add", "kind": "doodad", "type": "ZRrk", "x": 0, "y": 0}])
    scene = flow._grid(project, catalog, corners=False)
    assert pathing.cells(project, scene[0].terrain, catalog, scene[2])[3] == "derived"
