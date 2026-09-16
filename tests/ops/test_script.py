import re

import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps, open_sample, sample_map_ids
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.elements import elements_edit
from wc3mcp.ops.info import info_edit, info_get
from wc3mcp.ops.placed import placed_edit, placed_list
from wc3mcp.ops.script import _mapinfo, _Objects, _placed, _world, balance, map_validate, script_build, script_validate
from wc3mcp.ops.triggers import _load, triggers_edit
from wc3mcp.project.workspace import MapProject
from wc3mcp.script import build

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


@pytest.fixture(scope="module")
def layers():
    cache = {}
    return lambda project: cache.setdefault(balance(project), Catalog(_storage(), balance=balance(project)))


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_script_build_keeps_editor_scripts(tmp_path, layers, map_id):
    arc = open_sample(map_id)
    if arc.read("war3map.wtg") is None:
        pytest.skip("no triggers")
    src = tmp_path / "map.w3x"
    src.write_bytes(arc.data)
    project = MapProject.open(src)
    catalog = layers(project)
    assert script_build(project, catalog)["changed"] is False
    if arc.read("war3map.j") is None:
        return
    tf, ct = _load(project, catalog.trigger_data)
    objects, scene = _Objects(project, catalog), _world(project, catalog)
    whole = build.new_script(tf, ct, catalog.trigger_data, scene, _placed(project, catalog, objects),
                             _mapinfo(project, catalog, objects, scene.terrain), reference=arc.read("war3map.j").decode("utf-8"))
    assert whole == arc.read("war3map.j").decode("utf-8")


def test_placed_objects_are_built_into_the_script(tmp_path, catalog):
    project = open_copy(tmp_path, ladder("war3map.j"))
    result = placed_edit(project, catalog, [
        {"op": "add", "kind": "unit", "type": "Hpal", "x": 128, "y": -256, "owner": 1, "hero": {"level": 3},
         "abilities": [{"id": "AHhb", "level": 2}], "inventory": [{"slot": 0, "item": "ratc"}], "life": 50,
         "drops": {"sets": [[{"item": "ratc", "chance": 60}]]}},
        {"op": "add", "kind": "item", "type": "ratc", "x": 64, "y": 64},
        {"op": "add", "kind": "destructible", "type": "LTbr", "x": 512, "y": 512,
         "drops": {"sets": [[{"item": "YiI1", "chance": 100}]]}}], verbose=True)
    hero, item, barrel = (next(x for x in placed_list(project, catalog, limit=5000)["items"] if x["ref"] == r)
                          for r in result["created"])
    triggers_edit(project, catalog, [{"op": "trigger", "name": "Uses", "script":
                                      f"function InitTrig_Uses takes nothing returns nothing\n"
                                      f"    call KillUnit( {hero['script_name']} )\nendfunction"}])
    assert script_build(project, catalog)["changed"]
    text = project.read("war3map.j").decode("utf-8").replace("\r\n", "\n")
    name = hero["script_name"]
    assert f"    unit                    {name}          = null\n" in text
    assert (f"    set {name} = BlzCreateUnitWithSkin( p, 'Hpal', 128.0, -256.0, 270.000, 'Hpal' )\n"
            f"    call SetHeroLevel( {name}, 3, false )\n    set life = GetUnitState( {name}, UNIT_STATE_LIFE )\n"
            f"    call SetUnitState( {name}, UNIT_STATE_LIFE, 0.50 * life )\n"
            f"    call SelectHeroSkill( {name}, 'AHhb' )\n    call SelectHeroSkill( {name}, 'AHhb' )\n"
            f"    call UnitAddItemToSlotById( {name}, 'ratc', 0 )\n") in text
    assert "function CreateUnitsForPlayer1 takes nothing returns nothing" in text and "call CreateUnitsForPlayer1(  )" in text
    assert "call RandomDistAddItem( 'ratc', 60 )\n        call RandomDistAddItem( -1, 40 )" in text
    assert "    call BlzCreateItemWithSkin( 'ratc', 64.0, 64.0, 'ratc' )" in text and "    call CreateAllItems(  )" in text
    assert "call TriggerAddAction( t, function SaveDyingWidget )" in text
    assert "call RandomDistAddItem( ChooseRandomItemEx( ITEM_TYPE_PERMANENT, 1 ), 100 )" in text
    main = text[text.index("function main takes"):]
    calls = [main.index(f"    call {fn}(  )") for fn in ("CreateAllDestructables", "CreateAllItems", "CreateAllUnits",
                                                             "InitBlizzard")]
    assert calls == sorted(calls)
    assert script_build(project, catalog)["changed"] is False
    assert script_validate(project, catalog)["ok"]

    placed_edit(project, catalog, [{"op": "delete", "ref": r} for r in (item["ref"], barrel["ref"])])
    script_build(project, catalog)
    text = project.read("war3map.j").decode("utf-8")
    assert "CreateAllItems" not in text and "Destructable Objects" not in text and "Doodad" not in text


def test_map_info_is_built_into_the_script(tmp_path, catalog):
    project = open_copy(tmp_path, ladder("war3map.j"))
    info_edit(project, [{"op": "set", "path": "players[0].race", "value": "orc"},
                        {"op": "set", "path": "author", "value": "Script Test"}])
    assert script_build(project, catalog)["changed"]
    text = project.read("war3map.j").decode("utf-8")
    assert "//   Map Author: Script Test" in text
    players = info_get(project)["players"]
    assert f"call SetPlayerRacePreference( Player({players[0]['id']}), RACE_PREF_ORC )" in text
    assert script_build(project, catalog)["changed"] is False and script_validate(project, catalog)["ok"]


def test_script_errors_point_at_their_trigger(tmp_path, catalog):
    project = open_copy(tmp_path, ladder("war3map.j"))
    triggers_edit(project, catalog, [{"op": "trigger", "name": "Broken", "actions": [
        {"fn": "CustomScriptCode", "args": ["call UndefinedThing()"]}]}])
    script_build(project, catalog)
    result = script_validate(project, catalog)
    assert not result["ok"] and result["language"] == "jass"
    assert [e["trigger"] for e in result["errors"]] == ["Broken"]


def test_lua_maps_are_rebuilt(tmp_path, layers):
    project = open_copy(tmp_path, ladder("war3map.lua"))
    catalog = layers(project)
    assert script_validate(project, catalog) | {"seconds": 0} == {
        "language": "lua", "file": "war3map.lua", "ok": True, "errors": [], "tool": "luacheck", "seconds": 0}
    text = "function InitTrig_Text()\r\n    print(Twice(2))\r\nend\r\n"
    triggers_edit(project, catalog, [
        HELLO, {"op": "header", "script": "-- helpers\nfunction Twice(x)\n    return 2 * x\nend"},
        {"op": "trigger", "name": "Text", "script": text},
        {"op": "trigger", "name": "Gui", "actions": [{"fn": "IfThenElseMultiple", "args": [], "if": [], "else": [],
                                                      "then": [{"fn": "CustomScriptCode", "args": ['print("then")']}]}]}])
    assert script_build(project, catalog) == {"changed": True, "language": "lua", "file": "war3map.lua"}
    lua = project.read("war3map.lua").decode("utf-8")
    assert "\r\nfunction InitTrig_Hello()\r\n" in lua and "\r\nInitTrig_Hello()\r\n" in lua
    # the map's own Lua passes through as the editor writes it: the header, custom text after an empty InitTrig, and
    # Custom Script actions with their JASS indentation
    assert "\r\n-- helpers\r\nfunction Twice(x)\r\n    return 2 * x\r\nend\r\n" in lua
    assert "\r\nfunction InitTrig_Text()\r\nend\r\n\r\n" + text + "\r\n" in lua
    assert '(Trig_Gui_Func001C()) then\r\n        print("then")\r\n' in lua
    assert script_build(project, catalog)["changed"] is False
    assert script_validate(project, catalog)["ok"]


def test_switching_the_script_language_generates_the_new_script(tmp_path, layers):
    project = open_copy(tmp_path, ladder("war3map.j"))
    catalog = layers(project)
    info_edit(project, [{"op": "set", "path": "script_language", "value": "lua"}])
    assert script_build(project, catalog) == {"changed": True, "language": "lua", "file": "war3map.lua"}
    assert "\r\nfunction main()\r\n" in project.read("war3map.lua").decode("utf-8")
    assert script_validate(project, catalog)["ok"] and map_validate(project, catalog)["errors"] == []
    project.delete("war3map.j")
    info_edit(project, [{"op": "set", "path": "script_language", "value": "jass"}])
    assert script_build(project, catalog) == {"changed": True, "language": "jass", "file": "war3map.j"}
    assert project.read("war3map.j") == open_sample("ladder:" + ladder("war3map.j").name).read("war3map.j")


def test_hand_written_lua_is_not_replaced(tmp_path, catalog):
    project = open_copy(tmp_path, ladder("war3map.lua"))
    project.write("war3map.lua", b"print('mine')\n")
    with pytest.raises(ToolError) as e:
        script_build(project, catalog)
    assert e.value.code == "not_editor_script" and project.read("war3map.lua") == b"print('mine')\n"
