import pytest

from corpus import HAVE_INSTALL, _storage
from wc3mcp.errors import ToolError
from wc3mcp.formats import blp, doo, imp, mmp, unitsdoo, w3c, w3e, w3i, w3r, w3s, wpm
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops import newmap
from wc3mcp.ops.info import info_get
from wc3mcp.ops.script import map_validate, script_build, script_validate
from wc3mcp.ops.triggers import triggers_tree

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance="Custom_V1")


def test_new_map_files_and_script(tmp_path, catalog):
    project = newmap.new_map(tmp_path / "Arena.w3x", catalog, width=96, height=64, tileset="V", players=3,
                             name="Arena", author="Tests")
    read = project.read
    t = w3e.parse(read("war3map.w3e"))
    assert (t.version, t.tileset, t.width, t.height) == (12, "V", 97, 65)
    assert t.tiles == [x.encode() for x in catalog.ids("tile") if x[0] == "V"] and len(t.cliff_tiles) == 2
    info = w3i.parse(read("war3map.w3i"))
    assert (info.version, info.playable_width, info.playable_height, len(info.players), len(info.forces)) == (39, 84, 52, 3, 1)
    left, bottom, right, top = info.camera_bounds[:4]
    assert left < right and bottom < top and t.offset_x < left and right < t.offset_x + 96 * 128
    starts = [u for u in unitsdoo.parse(read("war3mapUnits.doo")).units if u.id == b"sloc"]
    assert [u.owner for u in starts] == [0, 1, 2]
    assert all(left <= u.x <= right and bottom <= u.y <= top for u in starts)
    assert [(p.start_x, p.start_y) for p in info.players] == [(u.x, u.y) for u in starts]
    pm = wpm.parse(read("war3map.wpm"))
    assert (pm.width, pm.height) == (384, 256) and len(read("war3map.shd")) == 384 * 256
    for name, codec in (("war3map.doo", doo), ("war3map.w3r", w3r), ("war3map.w3c", w3c), ("war3map.w3s", w3s),
                        ("war3map.mmp", mmp), ("war3map.imp", imp)):
        assert codec.serialize(codec.parse(read(name))) == read(name), name
    assert info_get(project)["name"] == "Arena" and info_get(project)["author"] == "Tests"
    assert [x["name"] for x in triggers_tree(project, catalog)["triggers"]] == ["Melee Initialization"]
    text = read("war3map.j").decode("utf-8")
    assert "// Arena\r\n" in text and "call SetPlayers( 3 )" in text and "function Trig_Melee_Initialization_Actions" in text
    assert script_build(project, catalog)["changed"] is False
    assert script_validate(project, catalog)["ok"] and map_validate(project, catalog)["errors"] == []
    assert project.status()["dirty"] == []
    # the game quits right after login on a map without a minimap; the editor saves a 256x256 JPEG without mipmaps
    preview = blp.parse(read("war3mapMap.blp"))
    assert (preview.compression, preview.width, preview.height, preview.has_mipmaps) == (blp.JPEG, 256, 256, 0)


def test_new_folder_map(tmp_path, catalog):
    project = newmap.new_map(tmp_path / "Folder Map.w3x", catalog, width=32, height=32, players=1, format="folder")
    assert (tmp_path / "Folder Map.w3x" / "war3map.j").is_file()
    assert w3e.parse(project.read("war3map.w3e")).width == 33


def test_new_lua_map(tmp_path, catalog):
    project = newmap.new_map(tmp_path / "Lua.w3x", catalog, players=2, name="Lua Arena", script_language="lua")
    assert info_get(project)["script_language"] == "lua"
    assert "war3map.j" not in {f["name"] for f in project.list_files()}
    text = project.read("war3map.lua").decode("utf-8")
    assert "\r\nfunction InitTrig_Melee_Initialization()\r\n" in text and "\r\nSetPlayers(2)\r\n" in text
    assert script_build(project, catalog)["changed"] is False
    assert script_validate(project, catalog)["ok"] and map_validate(project, catalog)["errors"] == []


def test_new_map_errors(tmp_path, catalog):
    (tmp_path / "Taken.w3x").write_bytes(b"x")
    bad = [({"path": tmp_path / "Taken.w3x"}, "exists"), ({"width": 33}, "bad_value"), ({"height": 512}, "bad_value"),
           ({"tileset": "?"}, "bad_value"), ({"tileset": "LL"}, "bad_value"), ({"players": 0}, "bad_value"),
           ({"players": 25}, "bad_value"), ({"script_language": "python"}, "bad_value"),
           ({"format": "zip"}, "bad_value")]
    for args, code in bad:
        with pytest.raises(ToolError) as e:
            newmap.new_map(**{"path": tmp_path / "New.w3x", "catalog": catalog, **args})
        assert e.value.code == code, args
        assert not (tmp_path / "New.w3x").exists()
