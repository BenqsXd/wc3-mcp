import shutil

import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.ai import ai_edit, ai_export, ai_get
from wc3mcp.ops.imports import imports_list
from wc3mcp.ops.script import map_validate, script_build, script_validate
from wc3mcp.ops.triggers import triggers_tree
from wc3mcp.project.workspace import MapProject

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance="Custom_V1")


def game_file(tmp_path, name="War3.w3mod:AI Scripts/WyrmMonger.wai"):
    path = tmp_path / name.rsplit("/", 1)[-1]
    path.write_bytes(_storage().read(name))
    return path


def test_view_of_a_game_ai(tmp_path, catalog):
    path = game_file(tmp_path)
    doc = ai_get(path, catalog)
    assert (doc["name"], doc["race"], doc["options"]["melee"]) == ("Wyrm Monger", "undead", True)
    assert doc["workers"] == {"gold": "uaco", "lumber": "ugho", "base": "unpl", "mine": "ugol"}
    assert doc["conditions"][1] == {"index": 4, "name": "Attack Enemy", "condition": {
        "fn": "OperatorCompareInteger", "args": [{"call": "FoodUsed"}, {"preset": "OperatorGreaterEq"}, "86"]}}
    assert doc["build"][2] == {"type": "unit", "id": "ugol", "town": "mine1", "condition": "Mine 2 Rebuild"}
    assert doc["harvest"][4]["condition"]["custom"]["fn"] == "OperatorCompareBoolean"
    assert doc["groups"][3]["units"][1] == {"id": "ugho", "quantity": 11, "maximum": 11, "condition": "Lumber Ghouls 7"}
    assert doc["heroes"][0]["id"] == "Udea" and len(doc["heroes"][0]["skills"]) == 3
    before = path.read_bytes()
    assert ai_edit(path, catalog, [{"op": "set", "path": "name", "value": "Wyrm Monger"}])["changed"] is False
    assert path.read_bytes() == before


def test_build_an_ai_from_scratch_and_export_it(tmp_path, catalog):
    path = tmp_path / "Raiders.wai"
    result = ai_edit(path, catalog, [
        {"op": "set", "path": "name", "value": "Raiders"},
        {"op": "set", "path": "options.melee", "value": True},
        {"op": "append", "path": "conditions", "value": {"name": "Rich", "condition": {
            "fn": "OperatorCompareInteger", "args": [{"call": "GetGold"}, {"preset": "OperatorGreater"}, 500]}}},
        {"op": "set", "path": "heroes[0]", "value": {"id": "Hpal", "skills": [["AHhb", "AHds", "AHhb", "AHad", "AHhb",
                                                                              "AHre", "AHds", "AHad", "AHds", "AHad"]] * 3}},
        {"op": "set", "path": "hero_orders.order_1_2_3", "value": 100},
        {"op": "append", "path": "build", "value": {"type": "unit", "id": "hbar", "town": "main"}},
        {"op": "append", "path": "build", "value": {"type": "unit", "id": "hero1", "condition": "Rich"}},
        {"op": "append", "path": "build", "value": {"type": "expansion", "condition": {"custom": {
            "fn": "OperatorCompareInteger", "args": [{"call": "GetMinesOwned"}, {"preset": "OperatorLess"}, 2]}}}},
        {"op": "append", "path": "harvest", "value": {"resource": "gold", "town": "mine0", "workers": 5}},
        {"op": "append", "path": "harvest", "value": {"resource": "lumber", "workers": "all_not_attacking"}},
        {"op": "set", "path": "groups[0].units", "value": [{"id": "hero1", "quantity": 1}, {"id": "hfoo", "quantity": "all"}]},
        {"op": "set", "path": "attack.minimum_group", "value": 0},
        {"op": "append", "path": "attack.waves", "value": {"group": 0, "delay": 60}}])
    assert result["created"] and result["changed"]
    doc = ai_get(path, catalog)
    assert doc["build"][1] == {"type": "unit", "id": "hero1", "town": "any", "condition": "Rich"}
    exported = ai_export(path, catalog)
    assert exported["validation"] == {"ok": True, "errors": []}
    text = (tmp_path / "Raiders.ai").read_text("utf-8")
    assert "    call SetMeleeAI(  )" in text and "    set gCond_Rich = ( GetGold(  ) > 500 )" in text
    assert "    if (gCond_Rich) then\n        call SetBuildAll( BUILD_UNIT, 1, hero_id, -1 )" in text.replace("\r\n", "\n")


@pytest.mark.parametrize("op, code", [
    ({"op": "set", "path": "name", "value": 'Bad "name"'}, "bad_value"),
    ({"op": "append", "path": "build", "value": {"type": "unit", "id": "hfoo", "condition": "Nope"}}, "bad_value"),
    ({"op": "append", "path": "conditions", "value": {"name": "X", "condition": {"fn": "OperatorCompareInteger",
                                                                                   "args": [1, "OperatorEqual", 2]}}},
     "invalid_condition"),
    ({"op": "set", "path": "hero_orders.order_1_2_3", "value": 60}, "bad_value"),
    ({"op": "set", "path": "attack.repeat_waves", "value": 9}, "bad_value"),
    ({"op": "set", "path": "object_data", "value": None}, "bad_op"),
])
def test_edit_errors_leave_the_file_alone(tmp_path, catalog, op, code):
    path = game_file(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ToolError) as e:
        ai_edit(path, catalog, [op])
    assert e.value.code == code and path.read_bytes() == before


def test_export_into_a_map_with_a_start_trigger(tmp_path, catalog):
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps")
    target = tmp_path / maps[0].name
    shutil.copyfile(maps[0], target)
    project = MapProject.open(target)
    path = game_file(tmp_path, "War3.w3mod:AI Scripts/GruntMaster.wai")
    result = ai_export(path, catalog, project=project, player=1)
    assert result["import"] == "war3mapImported\\GruntMaster.ai" and result["trigger"] == "Start AI GruntMaster"
    assert any(i["path"].replace("/", "\\") == result["import"] for i in imports_list(project))
    assert "Start AI GruntMaster" in [t["name"] for t in triggers_tree(project, catalog)["triggers"]]
    script_build(project, catalog)
    text = project.read("war3map.j" if "war3map.j" in {f["name"] for f in project.list_files()} else "war3map.lua")
    assert b"StartMeleeAI" in text and b"GruntMaster.ai" in text
    assert script_validate(project, catalog)["ok"] and map_validate(project, catalog)["errors"] == []
