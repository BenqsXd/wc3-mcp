import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps, open_sample
from wc3mcp.errors import ToolError
from wc3mcp.formats import wct, wtg
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.triggers import SCRIPT_WARNING, trigger_get, triggers_edit, triggers_tree, wrap_script
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
    ({"op": "trigger", "name": "Bad", "run_on_init": True, "actions": []}, "bad_value"),  # the editor ignores it on GUI
    ({"op": "trigger", "name": "Melee Initialization", "run_on_init": True}, "bad_value"),
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


def test_script_triggers_get_the_editors_wrapper(melee, catalog):
    result = triggers_edit(melee, catalog, [
        {"op": "trigger", "name": "Bare Actions", "script": 'call BJDebugMsg("hello")\n'}])
    assert any("wrapped the script in Trig_Bare_Actions_Actions" in w for w in result["warnings"])
    script = trigger_get(melee, catalog, "Bare Actions")["script"]
    assert "function Trig_Bare_Actions_Actions takes nothing returns nothing" in script
    assert 'call BJDebugMsg("hello")' in script and "set gg_trg_Bare_Actions = CreateTrigger(  )" in script
    assert "call TriggerAddAction( gg_trg_Bare_Actions, function Trig_Bare_Actions_Actions )" in script

    # a script that brings its own functions only needs the wrapper
    triggers_edit(melee, catalog, [{"op": "trigger", "name": "Own Function", "script": (
        "function Report takes nothing returns nothing\n    call BJDebugMsg(\"x\")\nendfunction\n")}])
    own = trigger_get(melee, catalog, "Own Function")["script"]
    assert "function InitTrig_Own_Function takes nothing returns nothing" in own
    assert "call TriggerAddAction( gg_trg_Own_Function, function Report )" in own

    # a complete script is kept as it is
    full = ("function InitTrig_Complete takes nothing returns nothing\n    set gg_trg_Complete = CreateTrigger(  )\n"
            "endfunction\n")
    assert triggers_edit(melee, catalog, [{"op": "trigger", "name": "Complete", "script": full}])["warnings"] == [
        SCRIPT_WARNING]
    assert trigger_get(melee, catalog, "Complete")["script"].replace("\r\n", "\n") == full


def test_validate_checks_the_script_right_away(melee, catalog):
    good = triggers_edit(melee, catalog, [
        {"op": "trigger", "name": "Fine", "script": 'call BJDebugMsg("ok")\n'}], validate=True)
    assert good["validation"]["ok"] and SCRIPT_WARNING not in good["warnings"]
    bad = triggers_edit(melee, catalog, [
        {"op": "trigger", "name": "Broken", "script": "call NoSuchNativeHere()\ncall BJDebugMsg(\"x\")\n"}],
        validate=True)
    assert not bad["validation"]["ok"]
    error = bad["validation"]["errors"][0]
    assert "NoSuchNativeHere" in error["message"] and error["trigger"] == "Broken" and error["script_line"] == 1


def test_script_replace_edits_part_of_a_script(melee, catalog):
    triggers_edit(melee, catalog, [
        {"op": "trigger", "name": "Test", "script": 'call BJDebugMsg("2900.0, -500.0")\ncall BJDebugMsg("b")\n'},
        {"op": "header", "script": "// x = 1\n"}])
    result = triggers_edit(melee, catalog, [
        {"op": "script_replace", "name": "Test", "old": "2900.0, -500.0", "new": "2900.0, -250.0"},
        {"op": "script_replace", "header": True, "old": "x = 1", "new": "x = 2"}], validate=True)
    assert result["validation"]["ok"]
    assert 'call BJDebugMsg("2900.0, -250.0")' in trigger_get(melee, catalog, "Test")["script"]
    assert trigger_get(melee, catalog)["script"].replace("\r\n", "\n") == "// x = 2\n"
    for op, code in (({"name": "Test", "old": "BJDebugMsg", "new": "x"}, "bad_value"),   # twice
                     ({"name": "Test", "old": "nowhere", "new": "x"}, "bad_value"),
                     ({"name": "Nobody", "old": "a", "new": "b"}, "not_found"),
                     ({"name": "Test", "old": "", "new": "b"}, "bad_op")):
        with pytest.raises(ToolError) as e:
            triggers_edit(melee, catalog, [{"op": "script_replace", **op}])
        assert e.value.code == code


def test_replacing_a_trigger_keeps_its_place_and_after_index_move_it(melee, catalog):
    """Trigger functions are emitted in tree order, so a replacement must not move the trigger to the end: the
    triggers that followed it would stop seeing its functions."""
    def order():
        return [t["name"] for t in triggers_tree(melee, catalog)["triggers"] if t["category"] == "Waves"]

    triggers_edit(melee, catalog, [{"op": "category", "name": "Waves"}] + [
        {"op": "trigger", "name": name, "category": "Waves", "script": f"function {name} takes nothing returns nothing\n"
         f"endfunction\nfunction InitTrig_{name} takes nothing returns nothing\nendfunction\n"}
        for name in ("Helpers", "Spawns", "Rounds")])
    assert order() == ["Helpers", "Spawns", "Rounds"]
    triggers_edit(melee, catalog, [{"op": "trigger", "name": "Helpers", "category": "Waves",
                                    "script": "function InitTrig_Helpers takes nothing returns nothing\nendfunction\n"}])
    assert order() == ["Helpers", "Spawns", "Rounds"]           # the same category: stays where it was
    triggers_edit(melee, catalog, [{"op": "trigger", "name": "Rounds", "index": 0}])
    assert order() == ["Rounds", "Helpers", "Spawns"]
    triggers_edit(melee, catalog, [{"op": "trigger", "name": "Rounds", "after": "Helpers"}])
    assert order() == ["Helpers", "Rounds", "Spawns"]
    triggers_edit(melee, catalog, [{"op": "trigger", "name": "Rounds", "after": None}])
    assert order() == ["Rounds", "Helpers", "Spawns"]
    for op, code in (({"op": "trigger", "name": "Rounds", "index": 9}, "bad_value"),
                     ({"op": "trigger", "name": "Rounds", "after": "Melee Initialization"}, "bad_value"),
                     ({"op": "trigger", "name": "Rounds", "after": "Rounds"}, "bad_value")):
        with pytest.raises(ToolError) as e:
            triggers_edit(melee, catalog, [op])
        assert e.value.code == code
    assert order() == ["Rounds", "Helpers", "Spawns"]           # a failed batch changes nothing


def test_a_handle_variable_type_the_editor_has_no_global_for_is_named(melee, catalog):
    triggers_edit(melee, catalog, [{"op": "variable", "name": "Camp", "type": "group"},
                                   {"op": "variable", "name": "Zone", "type": "rect"},
                                   {"op": "variable", "name": "Veil", "type": "fogmodifier"}])
    assert {v["name"]: v["type"] for v in triggers_tree(melee, catalog)["variables"]} == {
        "Camp": "group", "Zone": "rect", "Veil": "fogmodifier"}
    with pytest.raises(ToolError) as e:
        triggers_edit(melee, catalog, [{"op": "variable", "name": "Pool", "type": "itempool"}])
    assert e.value.code == "bad_value" and "ChooseRandomItemEx" in e.value.hint
    with pytest.raises(ToolError) as e:
        triggers_edit(melee, catalog, [{"op": "variable", "name": "Where", "type": "point"}])
    assert '"location"' in e.value.hint
    with pytest.raises(ToolError) as e:
        triggers_edit(melee, catalog, [{"op": "variable", "name": "Nope", "type": "spaceship"}])
    assert "data_search kind=trigger_type" in e.value.hint


from wc3mcp.ops.triggers import wrap_script  # noqa: E402


def test_a_library_trigger_gets_an_init_that_registers_nothing():
    """A script of helper functions that all take parameters: registering one fails pjass."""
    text = "function Lib_Add takes integer a, integer b returns integer\n    return a + b\nendfunction\n"
    script, note, _ = wrap_script("Lib", text, lua=False)
    assert "TriggerAddAction" not in script and "function InitTrig_Lib takes nothing returns nothing" in script
    assert "registers nothing" in note


def test_the_first_parameterless_function_is_the_action_when_no_trig_actions_exists():
    text = ("function Helper takes unit u returns nothing\nendfunction\n"
            "function Run takes nothing returns nothing\nendfunction\n")
    script, note, _ = wrap_script("T", text, lua=False)
    assert "call TriggerAddAction( gg_trg_T, function Run )" in script and "Run" in note
