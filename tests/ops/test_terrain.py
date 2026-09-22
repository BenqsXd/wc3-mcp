import io
import json
import math

import pytest
from PIL import Image

from corpus import HAVE_INSTALL, _storage, ladder_maps
from wc3mcp.errors import ToolError
from wc3mcp.formats import w3e
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops import terrain
from wc3mcp.project.workspace import MapProject

needs_maps = pytest.mark.skipif(not HAVE_INSTALL or not ladder_maps(), reason="needs the install and ladder maps")


def flat(size: int = 9, version: int = 11) -> w3e.Terrain:
    n = size * size
    return w3e.Terrain(version, "L", 0, [b"Ldrt"], [b"CLdi"], size, size, -512.0, -512.0, [0x2000] * n, [0] * n,
                       [0] * n, [0] * n, [2] * n)


def height(t, x, y) -> float:
    return (t.heights[((y + 512) // 128) * t.width + (x + 512) // 128] - 0x2000) / 4


def brush(t, *ops):
    b = terrain._Brush(t)
    for i, op in enumerate(ops):
        b.apply(op, f"ops[{i}]")
    return t


def error(fn, *args) -> ToolError:
    with pytest.raises(ToolError) as e:
        fn(*args)
    return e.value


def test_raise_lower_falloff_and_clamping():
    t = brush(flat(), {"op": "raise", "x": 0, "y": 0, "radius": 256, "amount": 64})
    assert (height(t, 0, 0), height(t, 128, 0), height(t, 256, 0), height(t, 384, 0)) == (64, 32, 0, 0)
    assert height(t, 128, 128) == pytest.approx(64 * 0.5 * (1 + math.cos(math.pi * math.sqrt(2) / 2)), abs=0.25)
    brush(t, {"op": "lower", "x": 0, "y": 0, "radius": 256, "amount": 16, "falloff": "flat"})
    assert (height(t, 0, 0), height(t, 128, 0), height(t, 256, 0)) == (48, 16, -16)
    brush(t, {"op": "raise", "x": 0, "y": 0, "radius": 100, "amount": 1e6, "falloff": "linear"})
    assert t.heights[4 * 9 + 4] == terrain.RAW_MAX
    brush(t, {"op": "lower", "x": 0, "y": 0, "radius": 100, "amount": 1e6})
    assert t.heights[4 * 9 + 4] == 0


def test_plateau_smooth_and_noise():
    t = brush(flat(), {"op": "plateau", "x": 0, "y": 0, "radius": 200, "height": 100})
    assert {height(t, x, y) for x in (-128, 0, 128) for y in (-128, 0, 128)} == {100}
    assert height(t, 256, 0) == 0
    t = flat()
    t.heights[4 * 9 + 4] = 0x2000 + 900 * 4
    brush(t, {"op": "smooth", "x": 0, "y": 0, "radius": 1})
    assert height(t, 0, 0) == 100
    brush(t, {"op": "plateau", "x": 0, "y": 0, "radius": 1})  # no height: the centre corner's
    assert height(t, 0, 0) == 100
    a = brush(flat(), {"op": "noise", "x": 0, "y": 0, "radius": 512, "amount": 50, "seed": 7})
    b = brush(flat(), {"op": "noise", "x": 0, "y": 0, "radius": 512, "amount": 50, "seed": 7})
    c = brush(flat(), {"op": "noise", "x": 0, "y": 0, "radius": 512, "amount": 50, "seed": 8})
    assert a.heights == b.heights != c.heights and a.heights != flat().heights


@pytest.mark.parametrize("version", sorted(w3e.VERSIONS))
def test_paint_cliff_water_and_flags(version):
    t = brush(flat(version=version), {"op": "paint", "tile": "Lgrs", "x": 0, "y": 0, "radius": 130},
              {"op": "cliff", "x": 0, "y": 0, "radius": 1, "level": 3, "cliff": "CLgr"},
              {"op": "water", "x": 256, "y": 256, "radius": 1, "level": 10},
              {"op": "ramp", "x": 0, "y": 0, "radius": 1}, {"op": "blight", "x": -128, "y": 0, "radius": 1},
              {"op": "boundary", "x": 512, "y": 512, "radius": 1})
    assert t.tiles == [b"Ldrt", b"Lgrs"] and t.cliff_tiles == [b"CLdi", b"CLgr"] and t.custom_tileset == 1
    center, edge = w3e.corner(t, 4, 4), w3e.corner(t, 4, 3)
    assert (center["texture"], center["layer"], center["cliff_texture"], center["ramp"]) == (1, 3, 1, True)
    assert center["ground_variation"] in terrain.VARIATIONS and edge["texture"] == 1 and w3e.corner(t, 2, 4)["texture"] == 0
    water = w3e.corner(t, 6, 6)
    assert water["water"] and (water["water_level"] - 0x2000) / 4 + terrain.WATER_OFFSET == pytest.approx(10, abs=0.25)
    assert w3e.corner(t, 3, 4)["blight"] and w3e.corner(t, 8, 8)["boundary"]
    brush(t, {"op": "water", "x": 256, "y": 256, "radius": 1, "level": None}, {"op": "ramp", "x": 0, "y": 0,
                                                                              "radius": 1, "value": False})
    assert not w3e.corner(t, 6, 6)["water"] and not w3e.corner(t, 4, 4)["ramp"]
    assert w3e.parse(w3e.serialize(t)) == t


def test_brush_errors():
    t = flat()
    t.tiles = [f"L{i:03d}".encode() for i in range(16)]
    bad = [({"op": "raise", "x": 99999, "y": 0, "radius": 64}, "bad_value"),
           ({"op": "raise", "x": 0, "y": 0, "radius": 0}, "bad_value"),
           ({"op": "raise", "x": 0, "y": 0, "radius": 64, "falloff": "steep"}, "bad_value"),
           ({"op": "raise", "x": 0, "y": 0, "radius": 64, "level": 3}, "bad_op"),
           ({"op": "paint", "x": 0, "y": 0, "radius": 64, "tile": "Lgrs"}, "bad_value"),
           ({"op": "paint", "x": 0, "y": 0, "radius": 64, "tile": "grass"}, "bad_value"),
           ({"op": "cliff", "x": 0, "y": 0, "radius": 64, "level": 16}, "bad_value"),
           ({"op": "smooth", "x": 0, "y": 0, "radius": 64, "strength": 2}, "bad_value")]
    for op, code in bad:
        assert error(terrain._Brush(t).apply, op, "ops[0]").code == code, op


@needs_maps
def test_get_edit_and_render_a_map(tmp_path):
    catalog = Catalog(_storage(), balance="Custom_V1")
    src = tmp_path / ladder_maps()[0].name
    src.write_bytes(ladder_maps()[0].read_bytes())
    project = MapProject.open(src)
    before = project.read("war3map.w3e")
    t = w3e.parse(before)
    doc = terrain.terrain_get(project, area=[-256, -256, 256, 512], layers=list(terrain.LAYERS))
    assert doc["corners"] == [t.width, t.height] and (doc["window"]["columns"], doc["window"]["rows"]) == (5, 7)
    assert set(doc["layers"]) == set(terrain.LAYERS) and len(doc["layers"]["height"][0]) == 5
    assert all(tile in doc["tiles"] for row in doc["layers"]["texture"] for tile in row)
    whole = terrain.terrain_get(project, step=8, layers=["cliff_level"])
    assert whole["window"]["columns"] == len(range(0, t.width, 8)) and list(whole["layers"]) == ["cliff_level"]
    assert error(terrain.terrain_get, project, None, ["colour"]).code == "bad_value"
    narrow = terrain.terrain_get(project, [1, -3200, 40, 1280], layers=["height"])   # between two corner lines in x
    assert narrow["window"]["columns"] == 1 and narrow["window"]["left"] == 0 and "x" in narrow["window"]["snapped"]
    assert "snapped" not in doc["window"]
    assert error(terrain.terrain_get, project, [99999, 99999, 100000, 100000]).code == "bad_value"

    result = terrain.terrain_edit(project, catalog, [{"op": "raise", "x": 0, "y": 0, "radius": 400, "amount": 100},
                                                     {"op": "paint", "x": 0, "y": 0, "radius": 200, "tile": "Lgrs"}])
    assert result["changed"] and result["warnings"] == [terrain.DERIVED_WARNING]
    after = terrain.terrain_get(project, area=[0, 0, 0, 0], layers=["height", "texture"])
    assert after["layers"]["texture"] == [["Lgrs"]] and after["layers"]["height"][0][0] == pytest.approx(
        doc["layers"]["height"][2][2] + 100, abs=0.25)
    edited = project.read("war3map.w3e")
    bad = [{"op": "raise", "x": 0, "y": 0, "radius": 64}, {"op": "paint", "x": 0, "y": 0, "radius": 64, "tile": "Zzzz"}]
    assert error(terrain.terrain_edit, project, catalog, bad).details["op_index"] == 1
    assert error(terrain.terrain_edit, project, catalog, [{"op": "dig"}]).code == "bad_op"
    assert project.read("war3map.w3e") == edited
    assert terrain.terrain_edit(project, catalog, [{"op": "plateau", "x": 0, "y": 0, "radius": 1}])["changed"] is False

    png = terrain.terrain_render(project, catalog, scale=2)
    image = Image.open(io.BytesIO(png))
    assert image.format == "PNG" and image.size == ((t.width - 1) * 2, (t.height - 1) * 2)
    assert len(image.getcolors(1 << 20)) > 20


def texture(t, x, y) -> str:
    c = w3e.corner(t, (x + 512) // 128, (y + 512) // 128)
    return t.tiles[c["texture"]].decode("latin-1")


def test_rect_path_and_whole_map_areas():
    t = flat()
    t.tiles.append(b"Lgrs")
    brush(t, {"op": "paint", "tile": "Lgrs"})                       # no area: the whole map
    assert {x.decode("latin-1") for x in t.tiles} == {"Ldrt", "Lgrs"}
    assert texture(t, -512, -512) == "Lgrs" and texture(t, 512, 512) == "Lgrs"
    brush(t, {"op": "paint", "tile": "Ldrt", "rect": [-512, -512, 0, 0]})
    assert texture(t, -128, -128) == "Ldrt" and texture(t, 128, 128) == "Lgrs"
    brush(t, {"op": "plateau", "rect": [-512, -512, 512, 512], "height": 0},
          {"op": "raise", "path": [[-512, 384], [512, 384]], "width": 200, "amount": 64, "falloff": "flat"})
    assert height(t, 0, 384) == 64 and height(t, 0, 0) == 0        # the stroke lifted its own line only
    assert error(brush, t, {"op": "paint", "tile": "Lgrs", "path": [[0, 0]]}).code == "bad_value"


def test_edit_reports_the_tile_palette(tmp_path):
    from wc3mcp.mpq.writer import write_archive

    src = tmp_path / "t.w3x"
    src.write_bytes(write_archive({"war3map.w3e": w3e.serialize(flat(version=12))}))
    project = MapProject.open(src)
    try:
        catalog = Catalog(_storage()) if HAVE_INSTALL else None
        before = terrain.terrain_get(project)["palette"]
        assert before == {"tiles": ["Ldrt"], "cliff_tiles": ["CLdi"], "free": 15, "limit": 16}
        result = terrain.terrain_edit(project, catalog, [{"op": "paint", "tile": "Lgrs", "rect": [-512, -512, 0, 0]}])
        assert result["palette_added"] == {"tiles": ["Lgrs"], "cliff_tiles": []}
        assert result["palette"]["tiles"] == ["Ldrt", "Lgrs"] and result["palette"]["free"] == 14
    finally:
        project.close(discard=True)


@needs_maps
def test_map_validate_warns_while_the_derived_files_are_stale(tmp_path):
    from wc3mcp.ops.script import map_validate

    src = tmp_path / ladder_maps()[0].name
    src.write_bytes(ladder_maps()[0].read_bytes())
    project = MapProject.open(src)
    catalog = Catalog(_storage(), balance="Custom_V1")
    try:
        assert not [w for w in map_validate(project, catalog)["warnings"] if w["check"] == "derived_files"]
        terrain.terrain_edit(project, catalog, [{"op": "raise", "x": 0, "y": 0, "radius": 256, "amount": 64}])
        stale = [w for w in map_validate(project, catalog)["warnings"] if w["check"] == "derived_files"]
        assert len(stale) == 1 and "editor_map open" in stale[0]["message"]
        project.note("terrain_edited", False)   # what editor_map save does
        assert not [w for w in map_validate(project, catalog)["warnings"] if w["check"] == "derived_files"]
    finally:
        project.close(discard=True)


@needs_maps
def test_render_marks_doodads_and_destructibles(tmp_path):
    from wc3mcp.ops.placed import placed_edit, placed_list

    catalog = Catalog(_storage())
    src = tmp_path / ladder_maps()[0].name
    src.write_bytes(ladder_maps()[0].read_bytes())
    project = MapProject.open(src)
    try:
        t = w3e.parse(project.read("war3map.w3e"))
        x, y = next((t.offset_x + k * 128, t.offset_y + k * 128) for k in range(12, t.width - 12)
                    if not placed_list(project, catalog, area=[t.offset_x + k * 128 - 300, t.offset_y + k * 128 - 300,
                                                               t.offset_x + k * 128 + 300, t.offset_y + k * 128 + 300])["total"])
        placed_edit(project, catalog, [{"op": "add", "kind": "destructible", "type": "LTlt", "x": x, "y": y}])
        scale = 8
        px = (int((x - t.offset_x) / 128 * scale), int((t.height - 1 - (y - t.offset_y) / 128) * scale))
        with_marks = Image.open(io.BytesIO(terrain.terrain_render(project, catalog, scale=scale)))
        plain = Image.open(io.BytesIO(terrain.terrain_render(project, catalog, scale=scale, doodads=False)))
        assert with_marks.getpixel(px) == (0, 90, 0) and plain.getpixel(px) != (0, 90, 0)
    finally:
        project.close(discard=True)


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs the install")
def test_unbuildable_tiles_warn_and_show_in_derived_pathing(tmp_path):
    from wc3mcp.mpq.writer import write_archive

    catalog = Catalog(_storage())
    assert catalog.search("tile", "Ybtl")[0].items() >= {"buildable": False, "walkable": True, "flyable": True}.items()
    assert catalog.get("tile", "Lrok", fields=["name", "buildable"])["fields"] == {"name": "Rock", "buildable": "0"}
    src = tmp_path / "t.w3x"
    src.write_bytes(write_archive({"war3map.w3e": w3e.serialize(flat(version=12))}))
    project = MapProject.open(src)
    try:
        result = terrain.terrain_edit(project, catalog, [{"op": "paint", "tile": "Ybtl", "rect": [-512, -512, 0, 512]},
                                                         {"op": "paint", "tile": "Lgrs", "x": 384, "y": 0, "radius": 1}])
        assert [w for w in result["warnings"] if "Ybtl" in w] == [
            "painted 45 corners with Ybtl (Brick): players cannot build on it (CreateUnit still places structures)"]
        assert not [w for w in result["warnings"] if "Lgrs" in w]
        terrain.terrain_edit(project, catalog, [{"op": "cliff", "x": 384, "y": 384, "radius": 1, "level": 3}])
        doc = terrain.terrain_get(project, layers=["pathing"], catalog=catalog)
        grid = doc["layers"]["pathing"]   # rows south to north, corners 128 apart from -512
        assert "wpm" not in doc["pathing_source"].split()[0] and grid[0][0] == "b" and grid[4][6] == ""
        assert grid[7][7] == "wb" and grid[6][6] == "wb" and grid[5][5] == ""
        image = Image.open(io.BytesIO(terrain.terrain_render(project, catalog, scale=4, objects=False, pathing=True)))
        red, green, _ = image.getpixel((2, 30))
        assert red > green + 60
    finally:
        project.close(discard=True)


@needs_maps
def test_preview_image_is_a_square_tga(tmp_path):
    """war3mapPreview.tga: what the map list shows instead of the minimap."""
    from wc3mcp.ops.terrain import preview

    catalog = Catalog(_storage())
    src = tmp_path / ladder_maps()[0].name
    src.write_bytes(ladder_maps()[0].read_bytes())
    project = MapProject.open(src)
    try:
        image = Image.open(io.BytesIO(preview(project, catalog, size=128)))
        assert image.format == "TGA" and image.size == (128, 128) and image.mode == "RGB"
    finally:
        project.close(discard=True)


@needs_maps
def test_terrain_get_packs_rows_and_summarises(tmp_path):
    """A whole map's terrain cell by cell is the biggest answer these tools give: runs and summary shrink it."""
    catalog = Catalog(_storage(), balance="Custom_V1")
    src = tmp_path / ladder_maps()[0].name
    src.write_bytes(ladder_maps()[0].read_bytes())
    project = MapProject.open(src)
    try:
        layers = ["height", "texture", "pathing"]
        grid = terrain.terrain_get(project, None, layers, 2, catalog)
        runs = terrain.terrain_get(project, None, layers, 2, catalog, format="runs")
        summary = terrain.terrain_get(project, None, layers, 2, catalog, format="summary")
        assert len(json.dumps(runs)) < len(json.dumps(grid))
        assert len(json.dumps(summary)) * 10 < len(json.dumps(grid))
        unpacked = [[value for value, count in row for _ in range(count)] for row in runs["runs"]["texture"]]
        assert unpacked == grid["layers"]["texture"]          # the same data, packed
        heights = summary["summary"]["height"]
        flat = [h for row in grid["layers"]["height"] for h in row]
        assert heights["min"] == round(min(flat), 1) and heights["max"] == round(max(flat), 1)
        assert sum(summary["summary"]["texture"]["counts"].values()) <= summary["summary"]["corners"]
        assert error(terrain.terrain_get, project, None, layers, 2, catalog, "pretty").code == "bad_value"
    finally:
        project.close(discard=True)


# ---- narrow areas snap to the nearest corner line -------------------------------------------------------------
def _snap_map(tmp_path, name):
    from wc3mcp.ops.newmap import new_map

    catalog = Catalog(_storage(), balance="Custom_V1")
    return new_map(str(tmp_path / name), catalog, width=64, height=64, tileset="L", players=2,
                   fill_tile="Lgrs"), catalog


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
def test_a_paint_stroke_between_two_corner_lines_paints_the_nearest_one(tmp_path):
    p, catalog = _snap_map(tmp_path, "S.w3x")
    result = terrain.terrain_edit(p, catalog, [{"op": "paint", "tile": "Ldrt", "path": [[-1000, 40], [1000, 40]],
                                                "width": 60}])
    assert result["snapped"] == ["ops[0]"]
    tiles = terrain.terrain_get(p, [-512, 0, -512, 128], ["texture"])["layers"]["texture"]
    assert [row[0] for row in tiles] == ["Ldrt", "Lgrs"]       # y 0 is 40 away, y 128 is 88 away


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
def test_a_small_circle_between_corners_paints_the_nearest_corner(tmp_path):
    p, catalog = _snap_map(tmp_path, "C.w3x")
    result = terrain.terrain_edit(p, catalog, [{"op": "paint", "tile": "Ldrt", "x": 30, "y": 20, "radius": 10}])
    assert result["snapped"] == ["ops[0]"]
    assert terrain.terrain_get(p, [0, 0, 0, 0], ["texture"])["layers"]["texture"][0][0] == "Ldrt"


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
def test_a_path_stroke_has_round_joins(tmp_path):
    p, catalog = _snap_map(tmp_path, "J.w3x")
    terrain.terrain_edit(p, catalog, [{"op": "paint", "tile": "Ldrt", "path": [[-1024, 0], [0, 0], [0, 1024]],
                                       "width": 512}])
    # the outside of the bend: 181 units from the polyline, inside the 256 half-width
    assert terrain.terrain_get(p, [128, -128, 128, -128], ["texture"])["layers"]["texture"][0][0] == "Ldrt"
