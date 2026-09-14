import pytest

from corpus import INSTALL, needs_install
from wc3mcp.casc.storage import open_storage
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog

pytestmark = needs_install


@pytest.fixture(scope="module")
def cat():
    return Catalog(open_storage(INSTALL), locale="enUS", balance=None, hd=True)  # base data: stable values


def test_unit_fields(cat):
    g = cat.get("unit", "hfoo")
    assert g["name"] == "Footman"
    assert g["fields"]["uhpm"]["name"] == "Hit Points Maximum (Base)"
    assert g["fields"]["uhpm"]["value"] == "420"
    assert g["fields"]["umdl"]["value"].lower().endswith("footman")


def test_ability_levels_and_specific_fields(cat):
    g = cat.get("ability", "AHbz", fields=["Hbz1", "atp1", "hem1"])
    assert g["levels"] == 3
    assert g["fields"]["Hbz1"]["values"] == ["6", "8", "10"]
    assert g["fields"]["atp1"]["values"][0] == "Blizzard - [|cffffcc00Level 1|r]"
    assert "hem1" not in g["fields"]  # a Data field that only applies to Ahem


def test_names_for_other_kinds(cat):
    assert cat.name("item", "ratf") == "Claws of Attack +15"
    assert cat.name("buff", "BHbd") == "Blizzard"
    assert cat.name("upgrade", "Rhme") == "Iron Forged Swords"
    assert cat.name("destructible", "LTlt") == "Summer Tree Wall"
    assert cat.name("doodad", "APms") == "Mushrooms"
    assert cat.name("tile", "Ldrt") == "Dirt"
    assert cat.name("cliff", "CLdi") == "Dirt Cliff"


def test_upgrade_level_names(cat):
    g = cat.get("upgrade", "Rhme", fields=["gnam"])
    assert g["levels"] == 3
    assert g["fields"]["gnam"]["values"] == ["Iron Forged Swords", "Steel Forged Swords", "Mithril Forged Swords"]


def test_search(cat):
    assert "Hamg" in [r["id"] for r in cat.search("unit", "archmage")]
    models = cat.search("model", "footman")
    assert models and all(m["id"].lower().endswith((".mdx", ".mdl")) for m in models)


def test_unknown_kind_and_id(cat):
    with pytest.raises(ToolError) as e:
        cat.get("spaceship", "x")
    assert e.value.code == "bad_kind"
    with pytest.raises(ToolError) as e:
        cat.get("unit", "zzzz")
    assert e.value.code == "not_found"
