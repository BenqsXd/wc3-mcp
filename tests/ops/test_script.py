import re

import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps, open_sample
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.elements import elements_edit
from wc3mcp.ops.script import map_validate, script_build, script_validate
from wc3mcp.ops.triggers import triggers_edit
from wc3mcp.project.workspace import MapProject

pytestmark = pytest.mark.skipif(not HAVE_INSTALL or not ladder_maps(), reason="needs the install and ladder maps")
HELLO = {"op": "trigger", "name": "Hello", "actions": [
    {"fn": "DisplayTextToForce", "args": [{"call": "GetPlayersAll"}, "Hi"]}]}


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)


def ladder(script: str):
    return next(p for p in ladder_maps() if open_sample("ladder:" + p.name).read(script) is not None)


def open_copy(tmp_path, path):
    src = tmp_path / path.name
    src.write_bytes(path.read_bytes())
    return MapProject.open(src)


def test_new_trigger_is_built_into_the_script(tmp_path, catalog):
    project = open_copy(tmp_path, ladder("war3map.j"))
    triggers_edit(project, catalog, [HELLO])
    result = script_build(project, catalog)
    assert result == {"changed": True, "language": "jass", "file": "war3map.j"}
    text = project.read("war3map.j").decode("utf-8")
    assert "function InitTrig_Hello takes nothing returns nothing" in text and "call InitTrig_Hello(  )" in text
    assert "    trigger                 gg_trg_Hello               = null" in text
    assert script_build(project, catalog)["changed"] is False
    assert script_validate(project, catalog)["ok"]
    assert map_validate(project, catalog)["errors"] == []


def test_regions_cameras_and_sounds_are_built_into_the_script(tmp_path, catalog):
    project = open_copy(tmp_path, ladder("war3map.j"))
    elements_edit(project, catalog, "region", [
        {"op": "upsert", "name": "Arena", "left": -256, "bottom": -256, "right": 256, "top": 256, "weather": "RAlr"}])
    elements_edit(project, catalog, "camera", [{"op": "upsert", "name": "Intro", "x": 128, "y": -64}])
    elements_edit(project, catalog, "sound", [
        {"op": "upsert", "name": "Hello", "path": "Units\\Human\\Footman\\FootmanYesAttack2.flac",
         "label": "FootmanYesAttack"}])
    assert script_build(project, catalog)["changed"]
    text = project.read("war3map.j").decode("utf-8")
    assert "set gg_rct_Arena = Rect( -256.0, -256.0, 256.0, 256.0 )" in text and "call CreateRegions(  )" in text
    assert "set gg_cam_Intro = CreateCameraSetup(  )" in text and "call CreateCameras(  )" in text
    duration = re.search(r"call SetSoundDuration\( gg_snd_Hello, (\d+) \)", text)
    assert duration and int(duration.group(1)) > 0 and "call InitSounds(  )" in text
    assert script_build(project, catalog)["changed"] is False
    assert script_validate(project, catalog)["ok"]
    elements_edit(project, catalog, "region", [{"op": "delete", "name": "Arena"}])
    script_build(project, catalog)
    assert "gg_rct_Arena" not in project.read("war3map.j").decode("utf-8")


def test_script_errors_point_at_their_trigger(tmp_path, catalog):
    project = open_copy(tmp_path, ladder("war3map.j"))
    triggers_edit(project, catalog, [{"op": "trigger", "name": "Broken", "actions": [
        {"fn": "CustomScriptCode", "args": ["call UndefinedThing()"]}]}])
    script_build(project, catalog)
    result = script_validate(project, catalog)
    assert not result["ok"] and result["language"] == "jass"
    assert [e["trigger"] for e in result["errors"]] == ["Broken"]


def test_lua_maps_are_validated_but_not_rebuilt(tmp_path, catalog):
    project = open_copy(tmp_path, ladder("war3map.lua"))
    with pytest.raises(ToolError) as e:
        script_build(project, catalog)
    assert e.value.code == "lua_not_supported"
    assert script_validate(project, catalog) | {"seconds": 0} == {
        "language": "lua", "file": "war3map.lua", "ok": True, "errors": [], "tool": "luacheck", "seconds": 0}
