import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps, open_sample
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.triggers import trigger_get, triggers_tree
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
