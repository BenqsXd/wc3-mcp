import io
import shutil

import numpy as np
import pytest
from PIL import Image

from corpus import HAVE_INSTALL, _storage, ladder_maps
from wc3mcp.errors import ToolError
from wc3mcp.formats import blp, mdl, mdx, texture
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


FOOTMAN_MODEL = {"game": "Units/Human/Footman/Footman.mdx"}


def test_model_info(storage):
    facts = assets.asset_info(FOOTMAN_MODEL, no_maps, storage)
    assert (facts["format"], facts["format_version"], facts["model_name"]) == ("mdx", 1800, "Footman")
    stand = next(s for s in facts["sequences"] if s["name"] == "Stand - 1")
    assert stand["looping"] and stand["duration"] == stand["interval"][1] - stand["interval"][0] > 0
    assert facts["textures"][0] == {"index": 0, "path": "Textures\\Footman.blp", "replaceable_id": 0}
    assert "Weapon Ref" in facts["attachments"] and facts["bones"] > 10 and facts["geosets"][0]["triangles"] > 100


def test_model_converts_between_mdx_and_mdl(tmp_path, storage):
    original = storage.read(storage.resolve("Units/Human/Footman/Footman.mdx"))
    result = assets.asset_convert(FOOTMAN_MODEL, {"file": str(tmp_path / "Footman.mdl")}, no_maps, storage)
    assert result["format"] == "mdl" and (tmp_path / "Footman.mdl").read_bytes().startswith(b"// MDL")
    assets.asset_convert({"file": str(tmp_path / "Footman.mdl")}, {"file": str(tmp_path / "back.bin")}, no_maps,
                         storage, fmt="mdx")
    assert (tmp_path / "back.bin").read_bytes() == original


def test_model_edits(tmp_path, storage):
    before = mdx.parse(storage.read(storage.resolve("Units/Human/Footman/Footman.mdx")))
    ops = [{"op": "retexture", "texture": "textures/footman.blp", "path": "war3mapImported\\Footman2.blp"},
           {"op": "rename_sequence", "sequence": "Stand - 1", "name": "Stand Ready"},
           {"op": "remove_sequence", "sequence": "Death"},
           {"op": "scale", "factor": 2},
           {"op": "team_color", "material": 0},
           {"op": "add_attachment", "name": "Custom Ref", "parent": 0, "position": [1, 2, 3]}]
    result = assets.asset_edit(FOOTMAN_MODEL, {"file": str(tmp_path / "Footman2.mdx")}, ops, no_maps, storage)
    assert result["ops"][0] == {"op": "retexture", "texture": 0} and result["ops"][5] == {"op": "add_attachment",
                                                                                          "object_id": 57}
    model = mdx.parse((tmp_path / "Footman2.mdx").read_bytes())
    assert mdx.chunk(model, "TEXS")[0]["path"] == "war3mapImported\\Footman2.blp"
    names = [s["name"] for s in mdx.chunk(model, "SEQS")]
    assert "Stand Ready" in names and "Death" not in names and len(names) == len(mdx.chunk(before, "SEQS")) - 1
    assert all(len(g["sequence_extents"]) == len(names) for g in mdx.chunk(model, "GEOS"))
    assert mdx.chunk(model, "GEOS")[0]["vertices"][:3] == [2 * x for x in mdx.chunk(before, "GEOS")[0]["vertices"][:3]]
    team, texture_layer = mdx.chunk(model, "MTLS")[0]["layers"]
    assert team["textures"][0]["texture_id"] == 1 and texture_layer["filter_mode"] == 2
    attachment = mdx.chunk(model, "ATCH")[-1]
    assert (attachment["node"]["name"], attachment["node"]["object_id"], attachment["attachment_id"]) == ("Custom Ref", 57, 9)
    assert mdx.chunk(model, "PIVT")[57] == [1.0, 2.0, 3.0] and len(mdx.chunk(model, "PIVT")) == 58
    assets.asset_edit(FOOTMAN_MODEL, {"file": str(tmp_path / "Footman2.mdl")}, ops, no_maps, storage)
    assert mdx.serialize(mdl.parse((tmp_path / "Footman2.mdl").read_bytes())) == (tmp_path / "Footman2.mdx").read_bytes()


def test_model_import_and_previews(tmp_path, storage):
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps")
    target = tmp_path / maps[0].name
    shutil.copyfile(maps[0], target)
    project = MapProject.open(target)
    project_for = {str(target): project}.__getitem__
    dest = {"map": str(target), "name": "war3mapImported\\Footman2.mdx"}
    assets.asset_edit(FOOTMAN_MODEL, dest, [{"op": "scale", "factor": 1.5}], project_for, storage)
    assert any(i["path"].replace("/", "\\") == dest["name"] for i in imports_list(project))
    assert map_validate(project, Catalog(_storage()))["errors"] == []
    for source in (dest, {"game": "War3.w3mod:_HD.w3mod:Units/Human/Footman/Footman.mdx"}):
        picture = Image.open(io.BytesIO(assets.asset_preview(source, project_for, storage, size=128)))
        assert picture.size == (128, 128) and np.asarray(picture.convert("RGB")).std() > 10


@pytest.mark.parametrize("dest, ops, code", [
    ({"file": "x.png"}, [], "bad_value"),
    ({"file": "x.mdx"}, [{"op": "resize", "width": 5, "height": 5}], "bad_op"),
    ({"file": "x.mdx"}, [{"op": "remove_sequence", "sequence": "Dance"}], "not_found"),
    ({"file": "x.mdx"}, [{"op": "scale", "factor": 0}], "bad_value"),
    ({"file": "x.mdx"}, [{"op": "team_color", "material": 99}], "bad_value"),
    ({"file": "x.mdx"}, [{"op": "add_attachment", "name": "A", "parent": "Nobody"}], "not_found"),
])
def test_model_errors(tmp_path, storage, dest, ops, code):
    with pytest.raises(ToolError) as e:
        assets.asset_edit(FOOTMAN_MODEL, {"file": str(tmp_path / dest["file"])}, ops, no_maps, storage)
    assert e.value.code == code
