import base64
import io

import pytest
from PIL import Image

from corpus import HAVE_INSTALL, _storage
from wc3mcp.errors import ToolError
from wc3mcp.formats import w3e
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops import heightmap
from wc3mcp.ops.newmap import new_map
from wc3mcp.ops.terrain import terrain_edit, terrain_get

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance="Custom_V1")


@pytest.fixture
def flat(tmp_path, catalog):
    """A 96x96 map of flat grass, the ground every landscape brush starts from."""
    return new_map(str(tmp_path / "Art.w3x"), catalog, width=96, height=96, tileset="L", players=2,
                   fill_tile="Lgrs"), catalog


def corners(project, area, layers=("height",)):
    """terrain_get's grids as {layer: [rows]}, with a "rows" view of them for the assertions below."""
    doc = terrain_get(project, area, list(layers), 1)
    grids = doc["layers"]
    doc["rows"] = [{name: grids[name][j] for name in grids} for j in range(len(next(iter(grids.values()))))]
    return doc


def height_at(project, x, y):
    doc = corners(project, [x - 1, y - 1, x + 1, y + 1])
    return doc["rows"][0]["height"][0]


def test_a_river_carves_a_bed_holds_water_and_leaves_its_banks_dry(flat):
    project, catalog = flat
    result = terrain_edit(project, catalog, [
        {"op": "river", "path": [[-3000, 0], [0, 500], [3000, 0]], "width": 512, "depth": 256,
         "bed": "Ldrt", "bank": "Ldrg", "water": True}])
    assert result["changed"]
    doc = corners(project, [-200, 200, 200, 800], ("height", "texture", "water"))
    middle = doc["rows"][len(doc["rows"]) // 2]
    assert min(middle["height"]) < -100                      # the bed is carved
    assert any(w is not None for row in doc["rows"] for w in row["water"])
    assert "Ldrt" in {tile for row in doc["rows"] for tile in row["texture"]}
    far = corners(project, [-200, 2000, 200, 2400], ("height", "water"))
    assert all(h == 0 for row in far["rows"] for h in row["height"])     # away from the river nothing moved
    assert all(w is None for row in far["rows"] for w in row["water"])
    with pytest.raises(ToolError) as e:
        terrain_edit(project, catalog, [{"op": "river", "rect": [-500, -500, 500, 500]}])
    assert e.value.code == "bad_value" and "path" in e.value.message


def test_a_coast_floods_below_the_waterline_and_puts_a_beach_above_it(flat):
    project, catalog = flat
    terrain_edit(project, catalog, [{"op": "raise", "rect": [0, -4000, 4000, 4000], "amount": 384, "falloff": "flat"}])
    terrain_edit(project, catalog, [
        {"op": "coast", "rect": [-4000, -4000, 4000, 4000], "water_level": 64, "beach": "Ldrt", "slope": 256}])
    west = corners(project, [-3000, -100, -2000, 100], ("water", "texture"))
    east = corners(project, [2000, -100, 3000, 100], ("water", "texture"))
    assert all(w is not None for row in west["rows"] for w in row["water"])    # the low half is under water
    assert all(w is None for row in east["rows"] for w in row["water"])        # the raised half stays dry
    shore = corners(project, [-200, -100, 200, 100], ("texture",))
    assert "Ldrt" in {tile for row in shore["rows"] for tile in row["texture"]}


def test_a_ridge_rises_along_its_path_and_erosion_wears_it_down(flat):
    project, catalog = flat
    terrain_edit(project, catalog, [
        {"op": "ridge", "path": [[-2000, -2000], [2000, 2000]], "width": 768, "height": 512, "roughness": 0.4,
         "seed": 3}])
    peak = max(h for row in corners(project, [-300, -300, 300, 300])["rows"] for h in row["height"])
    assert peak > 300
    rough = [h for row in corners(project, [-2000, -2000, 2000, 2000])["rows"] for h in row["height"]]
    terrain_edit(project, catalog, [
        {"op": "erosion", "rect": [-2000, -2000, 2000, 2000], "passes": 6, "strength": 0.8, "talus": 32}])
    smooth = [h for row in corners(project, [-2000, -2000, 2000, 2000])["rows"] for h in row["height"]]
    assert _slope(smooth) < _slope(rough)                     # erosion takes the steepness out
    assert max(smooth) > 150                                  # without flattening the ridge away


def _slope(values):
    return sum(abs(b - a) for a, b in zip(values, values[1:])) / max(len(values) - 1, 1)


def test_terrace_puts_the_ground_on_steps(flat):
    project, catalog = flat
    terrain_edit(project, catalog, [{"op": "noise", "rect": [-2000, -2000, 2000, 2000], "amount": 200, "seed": 1}])
    terrain_edit(project, catalog, [{"op": "terrace", "rect": [-2000, -2000, 2000, 2000], "step": 128}])
    heights = {round(h, 3) for row in corners(project, [-2000, -2000, 2000, 2000])["rows"] for h in row["height"]}
    assert heights and all(abs(h % 128) < 0.5 or abs(abs(h % 128) - 128) < 0.5 for h in heights)
    with pytest.raises(ToolError) as e:
        terrain_edit(project, catalog, [{"op": "terrace", "step": 0}])
    assert e.value.code == "bad_value"


def test_blend_speckles_only_the_seam_between_two_tiles(flat):
    project, catalog = flat
    terrain_edit(project, catalog, [{"op": "paint", "tile": "Ldrt", "rect": [-4000, -4000, 0, 4000]}])
    before = _tiles(project, [-3000, -3000, -2000, -2000])
    terrain_edit(project, catalog, [
        {"op": "blend", "rect": [-4000, -4000, 4000, 4000], "tiles": ["Lgrs", "Ldrt"], "amount": 0.8, "seed": 2}])
    seam = _tiles(project, [-300, -300, 300, 300])
    assert len(seam) == 2                                     # both tiles now appear either side of the line
    assert _tiles(project, [-3000, -3000, -2000, -2000]) == before   # far from the seam nothing changed
    with pytest.raises(ToolError) as e:
        terrain_edit(project, catalog, [{"op": "blend", "tiles": ["Lgrs", "Ybtl"]}])
    assert e.value.code == "bad_value" and "palette" in e.value.message


def _tiles(project, area):
    return {tile for row in corners(project, area, ("texture",))["rows"] for tile in row["texture"]}


def test_stamp_copies_a_patch_and_can_turn_it(flat):
    project, catalog = flat
    terrain_edit(project, catalog, [
        {"op": "plateau", "rect": [-3000, -3000, -2000, -2500], "height": 256},
        {"op": "paint", "tile": "Lrok", "rect": [-3000, -3000, -2000, -2500]}])
    terrain_edit(project, catalog, [
        {"op": "stamp", "from": [-3000, -3000, -2000, -2500], "to": [2000, 2000]}])
    copied = corners(project, [1500, 1800, 2500, 2200], ("height", "texture"))
    assert max(h for row in copied["rows"] for h in row["height"]) > 200
    assert "Lrok" in {tile for row in copied["rows"] for tile in row["texture"]}
    terrain_edit(project, catalog, [
        {"op": "stamp", "from": [-3000, -3000, -2500, -2500], "to": [0, 2000], "rotate": 90}])
    assert max(h for row in corners(project, [-300, 1700, 300, 2300])["rows"] for h in row["height"]) > 200
    for op, code in (({"op": "stamp", "from": [-3000, -3000, -2000, -2500], "to": [0, 0], "rotate": 90}, "bad_value"),
                     ({"op": "stamp", "from": [-3000, -3000, -2000, -2500], "to": [99999, 99999]}, "bad_value"),
                     ({"op": "stamp", "from": [0, 0], "to": [0, 0]}, "bad_value")):
        with pytest.raises(ToolError) as e:
            terrain_edit(project, catalog, [op])
        assert e.value.code == code, op


def test_a_heightmap_goes_in_and_comes_back_out(flat):
    project, catalog = flat
    picture = Image.new("L", (32, 32), 0)
    for x in range(16, 32):
        for y in range(32):
            picture.putpixel((x, y), 255)
    data = io.BytesIO()
    picture.save(data, format="PNG")
    terrain_edit(project, catalog, [
        {"op": "heightmap", "content_base64": base64.b64encode(data.getvalue()).decode(), "amount": 512,
         "rect": [-2000, -2000, 2000, 2000]}])
    west = height_at(project, -1500, 0)
    east = height_at(project, 1500, 0)
    assert west < 100 and east > 400                           # the white half of the picture is the high half
    exported = heightmap.export(_terrain(project), [-2000, -2000, 2000, 2000])
    read_back = Image.open(io.BytesIO(exported))
    window = corners(project, [-2000, -2000, 2000, 2000])["window"]
    assert read_back.mode == "I;16" and read_back.size == (window["columns"], window["rows"])
    span = heightmap.export_range(_terrain(project), [-2000, -2000, 2000, 2000])
    assert span["amount"] > 400 and abs(span["base"]) < 100
    other = new_map(str(_new_path(project)), catalog, width=96, height=96, tileset="L", players=2, fill_tile="Lgrs")
    terrain_edit(other, catalog, [
        {"op": "heightmap", "content_base64": base64.b64encode(exported).decode(), "rect": [-2000, -2000, 2000, 2000],
         "amount": span["amount"], "base": span["base"]}])
    assert abs(height_at(other, 1500, 0) - east) < 40           # the round trip reproduces the shape
    with pytest.raises(ToolError) as e:
        terrain_edit(project, catalog, [{"op": "heightmap", "source": "C:/nope/missing.png"}])
    assert e.value.code == "not_found"
    with pytest.raises(ToolError) as e:
        terrain_edit(project, catalog, [{"op": "heightmap", "content_base64": base64.b64encode(b"junk").decode()}])
    assert e.value.code == "bad_file"


def _terrain(project):
    return w3e.parse(project.read("war3map.w3e"))


def _new_path(project):
    from pathlib import Path

    return Path(project.m["source"]).with_name("Second.w3x")
