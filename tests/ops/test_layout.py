import math
import random

import pytest

from corpus import HAVE_INSTALL, _storage
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops import layout
from wc3mcp.ops.layout import along_path, blocks, layout_check, noise, poisson
from wc3mcp.ops.newmap import new_map
from wc3mcp.ops.placed import placed_edit, placed_list

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


def test_poisson_keeps_its_distance_and_fills_the_area():
    points = poisson(random.Random(1), (0, 0, 4000, 4000), lambda x, y: 200, 20000)
    assert 250 < len(points) < 400                      # hexagonal packing of a 4000x4000 area at 200 apart
    for i, (x, y) in enumerate(points):
        for px, py in points[i + 1:]:
            assert math.hypot(px - x, py - y) >= 199.9
    corners = {(x > 2000, y > 2000) for x, y in points}
    assert len(corners) == 4                            # every quarter of the area got points
    dense = poisson(random.Random(1), (0, 0, 4000, 4000), lambda x, y: 200 if x < 2000 else 600, 20000)
    left = sum(1 for x, _ in dense if x < 2000)
    assert left > (len(dense) - left) * 3               # the radius function thins the right half


def test_noise_is_smooth_and_repeatable():
    at = noise(7, cell=512)
    assert at(100, 100) == at(100, 100) and 0 <= at(100, 100) <= 1
    assert abs(at(100, 100) - at(110, 100)) < 0.1       # smooth, not white noise
    assert noise(8, cell=512)(100, 100) != at(100, 100)


def test_along_path_and_blocks():
    points = along_path([(0, 0), (1000, 0)], 250)
    assert [(round(x), round(y), round(a)) for x, y, a in points] == [
        (0, 0, 0), (250, 0, 0), (500, 0, 0), (750, 0, 0), (1000, 0, 0)]
    turn = along_path([(0, 0), (0, 500)], 500)
    assert round(turn[0][2]) == 90
    lots, streets = blocks((0, 0, 2000, 2000), 600, 600, 200)
    assert len(lots) == 4 and lots[0] == (0, 0, 600, 600) and lots[-1] == (800, 800, 1400, 1400)
    assert len(streets) == 6 and streets[0] == [[-100.0, -100.0], [-100.0, 2100.0]]


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance="Custom_V1")


@pytest.fixture
def town_map(tmp_path, catalog):
    return new_map(str(tmp_path / "Layout.w3x"), catalog, width=96, height=96, tileset="L", players=2,
                   fill_tile="Lgrs"), catalog


def test_forest_thins_toward_its_edge_and_keeps_out_of_the_exclusion(town_map):
    project, catalog = town_map
    result = placed_edit(project, catalog, [
        {"op": "forest", "kind": "destructible", "types": {"LTlt": 1}, "rect": [-3000, -3000, 3000, 3000],
         "spacing": 160, "density": 1.0, "edge": 900, "seed": 3, "on_tiles": ["Lgrs"],
         "exclude": [{"x": 0, "y": 0, "radius": 800}]}])
    trees = [o for o in placed_list(project, catalog, kind="destructible", limit=5000)["items"]]
    assert 250 < len(trees) < 1600 and result["layout"][0].endswith("destructible(s) in the wood")
    assert all(math.hypot(t["x"], t["y"]) > 795 for t in trees)          # nothing inside the exclusion
    middle = [t for t in trees if abs(t["x"]) < 1500 and abs(t["y"]) < 1500]
    rim = [t for t in trees if max(abs(t["x"]), abs(t["y"])) > 2400]
    assert _density(middle, 3000 * 3000 - math.pi * 800 ** 2) > _density(rim, 4 * 600 * 6000)
    assert all(-3000 <= t["x"] <= 3000 and -3000 <= t["y"] <= 3000 for t in trees)


def _density(objects, area):
    return len(objects) / area


def test_line_places_props_along_a_path_facing_it(town_map):
    project, catalog = town_map
    road = [[-2000, 0], [2000, 0]]
    placed_edit(project, catalog, [
        {"op": "line", "kind": "doodad", "types": ["XOcl"], "path": road, "spacing": 400, "offset": 200,
         "sides": "both", "face": "out", "seed": 1}])
    lamps = placed_list(project, catalog, kind="doodad", limit=5000)["items"]
    assert len(lamps) == 22                                              # 11 steps, both sides
    assert sorted({round(o["y"]) for o in lamps}) == [-200, 200]         # an even row either side of the road
    assert sorted({round(o["angle"]) for o in lamps}) == [90, 270]       # facing away from the road
    xs = sorted({round(o["x"]) for o in lamps})
    assert xs == list(range(-2000, 2001, 400))


def test_town_builds_blocks_whose_houses_face_the_street(town_map):
    project, catalog = town_map
    result = placed_edit(project, catalog, [
        {"op": "town", "kind": "unit", "types": {"hhou": 1}, "rect": [-1500, -1500, 1500, 1500], "block": [900, 900],
         "street": 400, "margin": 150, "spacing": 300, "owner": 0, "props": {"XOcl": 1}, "seed": 2}])
    houses = placed_list(project, catalog, kind="unit", limit=5000)["items"]
    assert len(houses) >= 20 and "block(s)" in result["layout"][0]
    assert {round(h["angle"]) for h in houses} <= {0, 90, 180, 270}      # every house faces its street
    assert result["streets"] and all(len(s) == 2 for s in result["streets"])
    lamps = placed_list(project, catalog, kind="doodad", limit=5000)["items"]
    assert lamps and all(round(o["angle"]) in (0, 90, 180, 270) for o in lamps)


def test_clear_removes_what_is_in_the_way(town_map):
    project, catalog = town_map
    placed_edit(project, catalog, [
        {"op": "forest", "kind": "destructible", "types": {"LTlt": 1}, "rect": [-2000, -2000, 2000, 2000],
         "spacing": 200, "seed": 4}])
    before = placed_list(project, catalog, kind="destructible")["total"]
    result = placed_edit(project, catalog, [{"op": "clear", "path": [[-2000, 0], [2000, 0]], "width": 600}])
    after = placed_list(project, catalog, kind="destructible", limit=5000)["items"]
    assert len(after) < before and "removed from the area" in result["layout"][0]
    assert all(abs(o["y"]) > 300 for o in after)


def test_cluster_thins_toward_the_rim_and_scales_its_objects(town_map):
    project, catalog = town_map
    placed_edit(project, catalog, [
        {"op": "cluster", "kind": "doodad", "types": ["ZPsh"], "x": 1000, "y": 1000, "radius": 800, "count": 200,
         "spacing": 100, "scale_range": [0.4, 1.3], "seed": 6}])
    rocks = placed_list(project, catalog, kind="doodad", limit=5000)["items"]
    assert rocks and all(math.hypot(o["x"] - 1000, o["y"] - 1000) <= 800 for o in rocks)
    near = [o for o in rocks if math.hypot(o["x"] - 1000, o["y"] - 1000) < 300]
    far = [o for o in rocks if math.hypot(o["x"] - 1000, o["y"] - 1000) > 600]
    assert min(o["scale"][0] for o in near) > max(o["scale"][0] for o in far)


def test_layout_check_reads_the_spacing_the_ground_and_the_reach(town_map):
    project, catalog = town_map
    placed_edit(project, catalog, [
        {"op": "forest", "kind": "destructible", "types": {"LTlt": 1}, "rect": [-3000, -3000, 3000, 3000],
         "spacing": 200, "seed": 5, "on_tiles": ["Lgrs"]}])
    doc = layout_check(project, catalog, kinds=["destructible"], min_distance=200)
    assert doc["count"] > 100 and doc["by_type"]["LTlt"] == doc["count"]
    assert doc["spacing"]["min"] >= 199 and doc["spacing"]["closer_than_min"] == 0
    assert 0.1 < doc["spacing"]["spread"] < 0.6          # neither a grid nor random darts
    assert doc["ground"] == {**doc["ground"], "on_water": 0, "unwalkable": 0, "by_tile": {"Lgrs": doc["count"]}}
    assert 0 < doc["reach"]["share"] <= 1 and doc["reach"]["walkable_corners"] > 0


def test_layout_ops_refuse_what_they_cannot_place(town_map):
    project, catalog = town_map
    for op, code in (({"op": "forest", "kind": "destructible", "types": {"nope": 1}}, "bad_value"),
                     ({"op": "forest", "kind": "destructible", "types": {"LTlt": 1}, "density": 4}, "bad_value"),
                     ({"op": "line", "kind": "doodad", "types": ["XOcl"], "path": [[0, 0]]}, "bad_value"),
                     ({"op": "line", "kind": "doodad", "types": ["XOcl"], "path": [[0, 0], [9, 9]],
                       "sides": "sideways"}, "bad_value"),
                     ({"op": "clear"}, "bad_value"),
                     ({"op": "town", "kind": "unit", "types": {"hhou": 1}, "block": [1]}, "bad_value"),
                     ({"op": "forest", "kind": "ability", "types": {"LTlt": 1}}, "bad_kind")):
        with pytest.raises(ToolError) as e:
            placed_edit(project, catalog, [op])
        assert e.value.code == code, op
    assert placed_list(project, catalog)["total"] == 2   # only the start locations: nothing was written
    assert set(layout.OP_KEYS) == {"forest", "line", "town", "cluster", "clear"}
