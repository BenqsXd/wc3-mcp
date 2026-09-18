import pytest

from corpus import HAVE_INSTALL, _storage
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.newmap import new_map
from wc3mcp.ops.recipes import RECIPES, recipe, recipe_list
from wc3mcp.ops.script import script_build, script_validate
from wc3mcp.ops.triggers import triggers_edit, triggers_tree

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance="Custom_V1")


def test_the_library_lists_every_recipe_with_its_parameters():
    listed = recipe_list()["recipes"]
    assert {row["name"] for row in listed} == set(RECIPES)
    assert all(row["does"] and isinstance(row["params"], dict) for row in listed)


@pytest.mark.parametrize("name", sorted(RECIPES))
def test_every_recipe_compiles_inside_a_real_map(name, tmp_path, catalog):
    """A recipe that does not compile is worse than no recipe, so pjass sees every one of them."""
    project = new_map(str(tmp_path / f"{name}.w3x"), catalog, width=64, height=64, tileset="L", players=2,
                      fill_tile="Lgrs")
    doc = recipe(name)
    assert doc["ops"][0] == {"op": "category", "name": "Systems"}
    triggers_edit(project, catalog, doc["ops"])
    script_build(project, catalog)
    script = project.read("war3map.j").decode("utf-8", "replace")
    assert f"function Trig_{doc['trigger']}_Actions" in script
    for variable in doc["variables"]:
        assert f"udg_{variable}" in script
    result = script_validate(project, catalog)
    assert result["ok"], result["errors"][:2]
    tree = triggers_tree(project, catalog)
    assert doc["trigger"] in [t["name"] for t in tree["triggers"]]
    assert next(t for t in tree["triggers"] if t["name"] == doc["trigger"])["run_on_init"]


def test_recipe_parameters_reach_the_script(tmp_path, catalog):
    waves = recipe("waves", {"spawn": [-1000, -1000], "target": [1500, 1500], "types": ["nfoh", "nhea"],
                             "interval": 20, "count": 4, "growth": 2, "owner": 10})
    assert "-1000.0" in waves["script"] and "1500.0" in waves["script"]
    assert "'nfoh'" in waves["script"] and "'nhea'" in waves["script"]
    assert "TimerStart(udg_Waves_Timer, 20.00, true" in waves["script"] and "Player(10)" in waves["script"]
    respawn = recipe("respawn", {"delay": 12, "owner": 6}, trigger="CreepsBack")
    assert respawn["trigger"] == "CreepsBack" and "12.00" in respawn["script"] and "Player(6)" in respawn["script"]
    assert "CreepsBack_Table" in respawn["variables"]
    quest = recipe("quest", {"title": 'The "Hold"', "description": "Stay alive", "required": False})
    assert "The 'Hold'" in quest["script"] and "QuestSetRequired(udg_Quest_Quest, false)" in quest["script"]


def test_a_recipe_refuses_what_it_cannot_build():
    for name, params, code in (("nope", None, "not_found"),
                               ("waves", {"types": ["toolong"]}, "bad_value"),
                               ("waves", {"interval": 0}, "bad_value"),
                               ("waves", {"spawn": [0]}, "bad_value"),
                               ("respawn", {"delay": "soon"}, "bad_value"),
                               ("respawn", {"nope": 1}, "bad_value"),
                               ("quest", {"title": 5}, "bad_value")):
        with pytest.raises(ToolError) as e:
            recipe(name, params)
        assert e.value.code == code, (name, params)
    with pytest.raises(ToolError) as e:
        recipe("camera", {}, trigger="9lives")
    assert e.value.code == "bad_value"
