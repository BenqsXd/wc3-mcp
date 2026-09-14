import json

import pytest

from corpus import HAVE_INSTALL, _storage, open_sample, sample_map_ids
from wc3mcp.errors import ToolError
from wc3mcp.formats import wtg
from wc3mcp.formats.wtg import Trigger, Variable
from wc3mcp.formats.wts import TriggerStrings
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.gamedata.triggerdata import ACTION, CALL, CONDITION, EVENT
from wc3mcp.ops.gui import Checker, Renderer, eca_json, ecas_from_json, script_name

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs TriggerData from the install")

SECTIONS = (("events", EVENT), ("conditions", CONDITION), ("actions", ACTION))
SPAWN = {
    "events": [{"fn": "TriggerRegisterTimerEventPeriodic", "args": ["1"]}],
    "conditions": [{"fn": "OperatorCompareInteger", "args": [{"var": "Count"}, {"preset": "OperatorGreater"}, "3"]}],
    "actions": [
        {"fn": "SetVariable", "args": [{"var": "Count"},
                                       {"call": "OperatorInt", "args": [{"var": "Count"}, {"preset": "OperatorAdd"}, "1"]}]},
        {"fn": "IfThenElseMultiple",
         "if": [{"fn": "OperatorCompareInteger", "args": [{"var": "Count"}, {"preset": "OperatorGreater"}, "10"]}],
         "then": [{"fn": "DisplayTextToForce", "args": [{"call": "GetPlayersAll"}, "Ten!"]}],
         "else": [{"fn": "TriggerSleepAction", "args": ["0.5"], "enabled": False}]},
    ],
}
VARIABLES = {"Count": Variable("Count", "integer"), "Heroes": Variable("Heroes", "unit", is_array=1, array_size=8)}


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)


def build(catalog, doc, variables=VARIABLES):
    return [e for key, kind in SECTIONS for e in ecas_from_json(doc.get(key), kind, catalog.trigger_data, variables, key)]


def as_json(ecas):
    return {key: [eca_json(e) for e in ecas if e.kind == kind] for key, kind in SECTIONS}


def test_script_names_follow_the_editor():
    assert script_name("Melee Initialization") == "Melee_Initialization"
    assert script_name("Doom06Cripple ") == "Doom06Cripple"                         # NightElf02: trailing spaces dropped
    assert script_name("  Footman01 End Movement") == "__Footman01_End_Movement"   # Human01: leading spaces kept


def test_json_converts_both_ways(catalog):
    ecas = build(catalog, SPAWN)
    assert [e.kind for e in ecas] == [EVENT, CONDITION, ACTION, ACTION]
    assert [(c.group, c.kind, c.enabled) for c in ecas[3].children] == [(0, CONDITION, 1), (1, ACTION, 1), (2, ACTION, 0)]
    add = ecas[2].params[1]
    assert (add.type, add.value, add.call.kind) == (wtg.FUNCTION, "OperatorInt", CALL)
    assert as_json(ecas) == SPAWN


def test_checker_accepts_valid_code_and_reports_mistakes(catalog):
    td = catalog.trigger_data
    ok = Checker(td, VARIABLES, set())
    ok.ecas(build(catalog, SPAWN), "trigger")
    assert ok.errors == [] and ok.warnings == []
    bad = Checker(td, VARIABLES, set())
    bad.ecas(build(catalog, {"actions": [
        {"fn": "KillUnit", "args": [{"var": "Count"}]},
        {"fn": "KillUnit", "args": [{"var": "Nope"}]},
        {"fn": "KillUnit", "args": [{"var": "Heroes"}]},
        {"fn": "TriggerSleepAction", "args": ["soon"]},
        {"fn": "KillUnit", "args": [None]},
        {"fn": "KillUnit", "args": [None], "enabled": False},
        {"fn": "TriggerExecute", "args": [{"var": "gg_trg_Missing"}]}]}), "trigger")
    assert len(bad.errors) == 5
    assert bad.errors[0] == "trigger[0].KillUnit.args[0]: expects unit, got integer"
    assert "unknown variable 'Nope'" in bad.errors[1] and "array" in bad.errors[2]
    assert "not a valid real" in bad.errors[3] and "not set" in bad.errors[4]
    assert bad.warnings == ["trigger[6].TriggerExecute.args[0]: no trigger matches 'gg_trg_Missing'"]


@pytest.mark.parametrize("item, code", [
    ({"fn": "MapInitializationEvent"}, "unknown_function"),
    ({"fn": "KillUnit"}, "bad_value"),
    ({"fn": "KillUnit", "args": [{"unit": 1}]}, "bad_value"),
    ({"fn": "KillUnit", "args": [{"call": "GetTriggerUnit"}], "colour": 1}, "bad_value"),
    ({"fn": "KillUnit", "args": [{"call": "NoSuchCall"}]}, "unknown_function"),
    ("KillUnit", "bad_value"),
])
def test_json_shape_errors(catalog, item, code):
    with pytest.raises(ToolError) as e:
        ecas_from_json([item], ACTION, catalog.trigger_data, VARIABLES, "actions")
    assert e.value.code == code and e.value.details["path"].startswith("actions[0]")


def test_render_editor_text(catalog):
    lines = Renderer(catalog.trigger_data, catalog, VARIABLES, TriggerStrings()).lines(build(catalog, SPAWN))
    assert lines == [
        "Events",
        "    Time - Every 1 seconds of game time",
        "Conditions",
        "    Count Greater than 3",
        "Actions",
        "    Set Count = (Count + 1)",
        "    If (All Conditions are True) then do (Then Actions) else do (Else Actions)",
        "        If - Conditions",
        "            Count Greater than 10",
        "        Then - Actions",
        "            Game - Display to (All players) the text: Ten!",
        "        Else - Actions",
        "            (disabled) Wait 0.5 seconds",
    ]


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_code_checks_clean_and_json_is_stable(map_id, catalog):
    td = catalog.trigger_data
    data = open_sample(map_id).read("war3map.wtg")
    if data is None:
        pytest.skip("map has no trigger data")
    tf = wtg.parse(data, td.arg_count)
    variables = {v.name: v for v in tf.variables}
    checker = Checker(td, variables, set())
    for t in tf.elements:
        if not isinstance(t, Trigger) or t.kind != wtg.TRIGGER or t.custom_text:
            continue
        if t.enabled:
            checker.ecas(t.ecas, t.name)
        doc = as_json(t.ecas)
        if '"children"' in json.dumps(doc):
            continue
        again = {key: [eca_json(e) for e in ecas_from_json(doc[key], kind, td, variables, key)] for key, kind in SECTIONS}
        assert again == doc, t.name
    assert checker.errors == []
