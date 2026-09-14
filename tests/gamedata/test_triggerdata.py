import pytest

from corpus import INSTALL, needs_install
from wc3mcp.casc.storage import open_storage
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.gamedata.triggerdata import ACTION, CALL, CONDITION, EVENT, Preset

pytestmark = needs_install


@pytest.fixture(scope="module")
def cat():
    return Catalog(open_storage(INSTALL), balance=None)


def test_function_signatures(cat):
    td = cat.trigger_data
    assert td.function(EVENT, "MapInitializationEvent").args == ()
    assert td.function(EVENT, "TriggerRegisterCommandEvent").args == ("abilcode", "unitorderEx")
    compare = td.function(CONDITION, "OperatorCompareInteger")
    assert compare.args == ("integer", "ComparisonOperator", "integer") and compare.display == "Integer Comparison"
    show = td.function(ACTION, "DisplayTextToForce")
    assert show.layout == ("Display to ", "~Player Group", " the text: ", "~Text") and show.category == "TC_GAME"
    assert td.function(ACTION, "TriggerSleepAction").defaults == ("2",)
    assert td.function(ACTION, "ForLoopAMultiple").display == "For Each Integer A, Do Multiple Actions"
    arith = td.function(CALL, "OperatorInt")
    assert arith.returns == "integer" and arith.args == ("integer", "ArithmeticOperator", "integer")
    assert td.function(ACTION, "GetTriggerUnit") is None and td.arg_count(CALL, "GetTriggerUnit") == 0
    assert td.arg_count(ACTION, "NoSuchFunction") is None and td.arg_count(9, "KillUnit") is None


def test_types_presets_and_categories(cat):
    td = cat.trigger_data
    assert td.types["unitcode"].base == "integer" and td.types["unitcode"].display == "Unit-Type"
    assert td.types["unit"].global_ok and td.base("unit") == "unit"
    assert td.presets["OperatorGreater"] == Preset("OperatorGreater", "ComparisonOperator", ">", "Greater than")
    assert td.categories["TC_GAME"] == ("Game", True) and td.categories["TC_WAIT"] == ("Wait", False)


def test_compatibility_rules(cat):
    td = cat.trigger_data
    assert td.compatible("unit", "unit") and td.compatible("AnyGlobal", "timer")
    assert td.compatible("StringExt", "string") and td.compatible("boolcall", "boolexpr")
    assert td.compatible("VarAsString_Real", "real") and td.compatible("handle", "unit")
    assert td.compatible("musicfile", "sound")
    assert not td.compatible("unit", "item") and not td.compatible("handle", "integer")
    assert not td.compatible("integer", "real")


def test_data_search_and_get(cat):
    hits = cat.search("trigger_function", "wait", limit=500)
    assert {"id": "TriggerSleepAction", "name": "Wait", "suffix": "action"} in hits
    assert cat.get("trigger_function", "DisplayTextToForce")["variants"] == [
        {"kind": "action", "args": ["force", "StringExt"], "returns": None,
         "text": "Display to ~Player Group the text: ~Text", "defaults": ["GetPlayersAll", "_"], "category": "Game"}]
    assert cat.get("trigger_type", "unitcode")["base"] == "integer"
    assert "OperatorGreater" in cat.get("trigger_type", "ComparisonOperator")["presets"]
    assert cat.get("trigger_preset", "OperatorGreater")["code"] == ">"
    with pytest.raises(ToolError) as e:
        cat.get("trigger_function", "NoSuchFunction")
    assert e.value.code == "not_found"
