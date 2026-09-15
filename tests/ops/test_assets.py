import io
import shutil

import numpy as np
import pytest
from PIL import Image

from corpus import HAVE_INSTALL, _storage, ladder_maps
from wc3mcp.errors import ToolError
from wc3mcp.formats import blp, texture
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops import assets
from wc3mcp.ops.imports import imports_list
from wc3mcp.ops.script import map_validate
from wc3mcp.project.workspace import MapProject

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
FOOTMAN = {"game": "ReplaceableTextures/CommandButtons/BTNFootman.dds"}


@pytest.fixture(scope="module")
def storage():
    return Catalog(_storage(), balance=None).storage


def no_maps(path):
    raise ToolError("not_open", f"map is not open: {path}")


def test_info_for_game_textures(storage):
    facts = assets.asset_info(FOOTMAN, no_maps, storage)
    assert (facts["format"], facts["width"], facts["compression"]) == ("dds", 64, "DXT5")
    old = assets.asset_info({"game": "War3.w3mod:ReplaceableTextures/CommandButtons/BTNBagofDust.blp"}, no_maps, storage)
    assert (old["format"], old["compression"], old["mipmaps"]) == ("blp", "jpeg", 7)


def test_convert_to_files_and_into_a_map(tmp_path, storage):
    png = tmp_path / "footman.png"
    result = assets.asset_convert(FOOTMAN, {"file": str(png)}, no_maps, storage)
    assert result["format"] == "png" and Image.open(png).size == (64, 64)
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps")
    target = tmp_path / maps[0].name
    shutil.copyfile(maps[0], target)
    project = MapProject.open(target)
    opened = {str(target): project}
    project_for = lambda p: opened[p]  # noqa: E731
    result = assets.asset_convert({"file": str(png)}, {"map": str(target), "name": "war3mapImported\\BTNTool.blp"},
                                  project_for, storage)
    assert result["import"] == "war3mapImported\\BTNTool.blp"
    data = project.read("war3mapImported\\BTNTool.blp")
    assert blp.parse(data).compression == blp.JPEG
    diff = np.abs(np.asarray(texture.decode(data)).astype(int) - np.asarray(Image.open(png).convert("RGBA")).astype(int))
    assert diff[..., :3].mean() < 4
    assert any(i["path"].replace("/", "\\") == "war3mapImported\\BTNTool.blp" for i in imports_list(project))
    assert map_validate(project, Catalog(_storage()))["errors"] == []


def test_icon_variants_match_the_games_style(tmp_path, storage):
    out = tmp_path / "DISBTNFootman.tga"
    assets.asset_edit(FOOTMAN, {"file": str(out)}, [{"op": "icon", "kind": "DISBTN"}], no_maps, storage)
    ours = np.asarray(Image.open(out).convert("RGBA")).astype(float)
    game = np.asarray(texture.decode(storage.read(storage.resolve(
        "ReplaceableTextures/CommandButtonsDisabled/DISBTNFootman.dds")))).astype(float)
    assert np.abs(ours - game)[..., :3].mean() < 8


def test_edit_ops_and_preview(tmp_path, storage):
    out = tmp_path / "edited.png"
    result = assets.asset_edit(FOOTMAN, {"file": str(out)}, [
        {"op": "resize", "width": 128, "height": 128}, {"op": "crop", "left": 0, "top": 0, "right": 100, "bottom": 80},
        {"op": "tint", "color": [255, 0, 0], "strength": 0.4}, {"op": "brightness", "factor": 1.2},
        {"op": "overlay", "source": FOOTMAN, "x": 10, "y": 10, "width": 32, "height": 32, "opacity": 0.5},
        {"op": "grayscale"}], no_maps, storage)
    assert (result["width"], result["height"]) == (100, 80)
    a = np.asarray(Image.open(out).convert("RGBA"))
    assert (a[..., 0] == a[..., 1]).all()
    preview = assets.asset_preview({"file": str(out)}, no_maps, storage, size=64)
    assert Image.open(io.BytesIO(preview)).size == (64, 51)


@pytest.mark.parametrize("args, code", [
    (({"game": "Nope/NoSuch.dds"}, {"file": "x.png"}, []), "not_found"),
    ((FOOTMAN, {"file": "x.gif"}, []), "bad_value"),
    ((FOOTMAN, {"file": "x.png"}, [{"op": "explode"}]), "bad_op"),
    ((FOOTMAN, {"file": "x.png"}, [{"op": "crop", "left": 0, "top": 0, "right": 999, "bottom": 5}]), "bad_value"),
    ((FOOTMAN, {"file": "x.png"}, [{"op": "icon", "kind": "ATC"}]), "bad_value"),
    (({"file": "x.png", "game": "y"}, {"file": "x.png"}, []), "bad_value"),
])
def test_errors(tmp_path, storage, args, code):
    source, dest, ops = args
    if "file" in dest:
        dest = {"file": str(tmp_path / dest["file"])}
    with pytest.raises(ToolError) as e:
        assets.asset_edit(source, dest, ops, no_maps, storage)
    assert e.value.code == code
