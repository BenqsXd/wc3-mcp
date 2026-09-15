import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps, open_sample
from wc3mcp.errors import ToolError
from wc3mcp.formats import wct, wtg
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.triggers import SCRIPT_WARNING, trigger_get, triggers_edit, triggers_tree
from wc3mcp.project.workspace import MapProject

WARCHASERS = "casc:Maps/Scenario/(4)WarChasers.w3m"
pytestmark = pytest.mark.skipif(not HAVE_INSTALL or not ladder_maps(),
                                reason="needs the Warcraft III install and ladder maps")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)


@pytest.fixture
def melee(tmp_path):
    src = tmp_path / ladder_maps()[0].name
    src.write_bytes(ladder_maps()[0].read_bytes())
    return MapProject.open(src)


@pytest.fixture
def warchasers(tmp_path):
    src = tmp_path / "WarChasers.w3m"
    src.write_bytes(open_sample(WARCHASERS).data)
    return MapProject.open(src)


def test_tree_of_a_melee_map(melee, catalog):
    tree = triggers_tree(melee, catalog)
    assert tree["map"] == ladder_maps()[0].name and tree["variables"] == [] and not tree["has_custom_script"]
    assert [(c["name"], c["parent"]) for c in tree["categories"]] == [("Initialization", None)]
    [melee_init] = tree["triggers"]
    assert {k: v for k, v in melee_init.items() if k != "id"} == {
        "name": "Melee Initialization", "category": "Initialization", "type": "gui", "enabled": True,
        "initially_on": True, "run_on_init": False, "functions": 9}


def test_tree_lists_variables(warchasers, catalog):
    tree = triggers_tree(warchasers, catalog)
    assert len(tree["variables"]) == 54 and len(tree["triggers"]) == 151
    assert (tree["variables"][0]["name"], tree["variables"][0]["type"]) == ("jugg3", "unit")


def test_get_gui_trigger(melee, catalog):
    doc = trigger_get(melee, catalog, "Melee Initialization")
    assert doc["events"] == [{"fn": "MapInitializationEvent"}] and doc["conditions"] == []
    assert doc["actions"][0] == {"fn": "MeleeStartingVisibility"} and len(doc["actions"]) == 8
    assert doc["description"] == "Default melee game initialization for all players"
    assert doc["text"].splitlines()[:5] == [
        "Events", "    Map initialization", "Conditions", "Actions",
        "    Melee Game - Use melee time of day (for all players)"]


def test_get_map_header_and_errors(melee, catalog):
    header = trigger_get(melee, catalog)
    assert header["type"] == "map" and header["script"] == "" and header["comment"].startswith("Enter map-specific")
    with pytest.raises(ToolError) as e:
        trigger_get(melee, catalog, "Nope")
    assert e.value.code == "not_found"
    melee.delete("war3map.wtg")
    with pytest.raises(ToolError) as e:
        triggers_tree(melee, catalog)
    assert e.value.code == "no_triggers"


SPAWN_ACTIONS = [
    {"fn": "SetVariable", "args": [{"var": "Count"},
                                   {"call": "OperatorInt", "args": [{"var": "Count"}, {"preset": "OperatorAdd"}, "1"]}]},
    {"fn": "IfThenElseMultiple",
     "if": [{"fn": "OperatorCompareInteger", "args": [{"var": "Count"}, {"preset": "OperatorGreater"}, "10"]}],
     "then": [{"fn": "DisplayTextToForce", "args": [{"call": "GetPlayersAll"}, "Ten!"]}]},
]


def test_create_category_variable_and_gui_trigger(melee, catalog):
    result = triggers_edit(melee, catalog, [
        {"op": "category", "name": "Spawns"},
        {"op": "variable", "name": "Count", "type": "integer", "initial": 0, "category": "Spawns"},
        {"op": "trigger", "name": "Spawn Tick", "category": "Spawns",
         "events": [{"fn": "TriggerRegisterTimerEventPeriodic", "args": [1]}], "actions": SPAWN_ACTIONS}])
    assert result == {"changed": True, "created": ["Spawns", "Count", "Spawn Tick"], "warnings": [SCRIPT_WARNING]}
    tree = triggers_tree(melee, catalog)
    assert [c["name"] for c in tree["categories"]] == ["Initialization", "Spawns"]
    assert tree["variables"] == [{"name": "Count", "type": "integer", "category": "Spawns", "initial": "0"}]
    assert (tree["triggers"][1]["name"], tree["triggers"][1]["category"]) == ("Spawn Tick", "Spawns")
    doc = trigger_get(melee, catalog, "Spawn Tick")
    assert doc["events"] == [{"fn": "TriggerRegisterTimerEventPeriodic", "args": ["1"]}]
    assert doc["actions"] == SPAWN_ACTIONS
    assert "    Time - Every 1 seconds of game time" in doc["text"].splitlines()
    tf = wtg.parse(melee.read("war3map.wtg"), catalog.trigger_data.arg_count)
    ids = [e.id for e in tf.elements]
    assert len(ids) == len(set(ids)) and [e.id >> 24 for e in tf.elements if e.name == "Spawn Tick"] == [3]
    assert len(wct.parse(melee.read("war3map.wct")).texts) == 2


def test_text_trigger_header_and_renames(melee, catalog):
    triggers_edit(melee, catalog, [
        {"op": "variable", "name": "Score", "type": "integer", "array_size": 12},
        {"op": "trigger", "name": "Setup", "script": "function InitTrig_Setup takes nothing returns nothing\nendfunction"},
        {"op": "trigger", "name": "Use Score", "actions": [
            {"fn": "SetVariable", "args": [{"var": "Score", "index": 1}, 5]},
            {"fn": "ConditionalTriggerExecute", "args": [{"var": "gg_trg_Setup"}]}]},
        {"op": "header", "script": "// shared helpers"}])
    assert trigger_get(melee, catalog, "Setup")["script"] == "function InitTrig_Setup takes nothing returns nothing\r\nendfunction"
    assert trigger_get(melee, catalog)["script"] == "// shared helpers"
    triggers_edit(melee, catalog, [{"op": "variable", "name": "Score", "new_name": "Points"},
                                   {"op": "trigger", "name": "Setup", "new_name": "Game Setup"}])
    actions = trigger_get(melee, catalog, "Use Score")["actions"]
    assert actions[0]["args"][0] == {"var": "Points", "index": "1"}
    assert actions[1]["args"] == [{"var": "gg_trg_Game_Setup"}]
    tree = triggers_tree(melee, catalog)
    assert tree["variables"][0]["array_size"] == 12 and tree["has_custom_script"]


def test_delete_rules(melee, catalog):
    triggers_edit(melee, catalog, [
        {"op": "variable", "name": "Count", "type": "integer"},
        {"op": "trigger", "name": "Counter", "actions": [{"fn": "SetVariable", "args": [{"var": "Count"}, 1]}]}])
    for op, code in (({"op": "delete", "what": "variable", "name": "Count"}, "in_use"),
                     ({"op": "delete", "what": "category", "name": "Initialization"}, "not_empty")):
        with pytest.raises(ToolError) as e:
            triggers_edit(melee, catalog, [op])
        assert e.value.code == code
    triggers_edit(melee, catalog, [{"op": "delete", "what": "trigger", "name": "Counter"},
                                   {"op": "delete", "what": "variable", "name": "Count"}])
    tree = triggers_tree(melee, catalog)
    assert [t["name"] for t in tree["triggers"]] == ["Melee Initialization"] and tree["variables"] == []
    tf = wtg.parse(melee.read("war3map.wtg"), catalog.trigger_data.arg_count)
    assert tf.counters[3][1] and tf.counters[6][1]
    assert len(wct.parse(melee.read("war3map.wct")).texts) == 1


@pytest.mark.parametrize("op, code", [
    ({"op": "trigger", "name": "Bad", "actions": [{"fn": "KillUnit", "args": [{"call": "GetPlayersAll"}]}]},
     "invalid_trigger"),
    ({"op": "trigger", "name": "Bad", "events": [{"fn": "KillUnit", "args": [{"call": "GetTriggerUnit"}]}]},
     "unknown_function"),
    ({"op": "trigger", "name": "Bad", "actions": [{"fn": "KillUnit"}]}, "bad_value"),
    ({"op": "trigger", "name": "Bad", "conditions": [{"fn": "OperatorCompareInteger",
      "args": [1, "OperatorEqualENE", 1]}]}, "invalid_trigger"),   # operator written as a literal, not a preset
    ({"op": "trigger", "name": "Melee_Initialization"}, "name_taken"),
    ({"op": "trigger", "name": "Bad", "category": "Nope"}, "not_found"),
    ({"op": "trigger", "name": "Bad", "script": "x", "actions": []}, "bad_op"),
    ({"op": "trigger", "name": "Bad", "colour": "red"}, "bad_op"),
    ({"op": "variable", "name": "1bad", "type": "integer"}, "bad_value"),
    ({"op": "variable", "name": "Ok", "type": "spaceship"}, "bad_value"),
    ({"op": "variable", "name": "Ok"}, "bad_op"),
    ({"op": "variable", "name": "Ok", "type": "integer", "initial": "many"}, "bad_value"),
    ({"op": "delete", "what": "unit", "name": "x"}, "bad_op"),
    ({"op": "explode"}, "bad_op"),
])
def test_edit_errors_are_atomic(melee, catalog, op, code):
    with pytest.raises(ToolError) as e:
        triggers_edit(melee, catalog, [{"op": "category", "name": "First"}, op])
    assert e.value.code == code and e.value.details["op_index"] == 1
    assert melee.status()["dirty"] == []
