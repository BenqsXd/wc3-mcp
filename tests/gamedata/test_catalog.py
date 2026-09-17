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


def test_icon_and_model_results_carry_their_object_data_reference(cat):
    icons = {r["ref"]: r for r in cat.search("icon", "*BTNSkillz*")}
    btn = icons[r"ReplaceableTextures\CommandButtons\BTNSkillz.blp"]
    assert btn["id"] == "War3.w3mod:ReplaceableTextures/CommandButtons/BTNSkillz.dds"
    assert sorted(btn["layers"]) == ["_DE", "_HD", "base"] and len(icons) == 2
    footman = {r["ref"]: r for r in cat.search("model", "*Footman*")}[r"Units\Human\Footman\Footman.mdl"]
    assert "base" in footman["layers"] and "_HD:_Teen" in footman["layers"]


def test_unknown_kind_and_id(cat):
    with pytest.raises(ToolError) as e:
        cat.get("spaceship", "x")
    assert e.value.code == "bad_kind"
    with pytest.raises(ToolError) as e:
        cat.get("unit", "zzzz")
    assert e.value.code == "not_found"


def test_field_netsafe_and_applicability(cat):
    units = {f.id: f for f in cat.fields("unit")}
    assert units["unam"].netsafe == "1" and units["uhpm"].netsafe == "0"
    abilities = {f.id: f for f in cat.fields("ability")}
    assert cat.applies("ability", "AHbz", abilities["Hbz1"])
    assert not cat.applies("ability", "AHbz", abilities["hem1"])
    assert cat.applies("unit", "hfoo", units["uhpm"])


def test_tiles_carry_their_tileset(cat):
    names = cat.tilesets()
    assert names["L"] == "Lordaeron Summer" and names["V"] == "Village"
    lordaeron = cat.search("tile", "", limit=500, tileset="Lordaeron Summer")
    assert lordaeron and all(r["id"][0] == "L" and r["tileset_name"] == "Lordaeron Summer" for r in lordaeron)
    assert {r["id"] for r in lordaeron} >= {"Lgrs", "Ldrt"}
    assert [r["id"] for r in cat.search("tile", "grass", tileset="L")] == [
        r["id"] for r in lordaeron if "grass" in r["name"].casefold()]
    assert cat.search("cliff", "", limit=50, tileset="L")[0]["id"][1] == "L"
    with pytest.raises(ToolError) as e:
        cat.search("tile", "", tileset="Nowhere")
    assert e.value.code == "not_found"


def test_doodads_by_tileset_and_model(cat):
    ashenvale = cat.search("doodad", "", limit=5000, tileset="A")
    ids = {r["id"] for r in ashenvale}
    assert "APms" in ids and "LOch" not in ids and "YOsp" in ids   # YOsp is on every tileset ("*")
    assert all(r["id"] in {x["id"] for x in cat.search("doodad", "", limit=5000)} for r in ashenvale)
    assert {r["id"]: r["model_ok"] for r in cat.search("doodad", "Grass Patch")}["LPgp"] is False
    assert {r["id"]: r["model_ok"] for r in cat.search("doodad", "", limit=5000, tileset="A")}["APms"] is True
    assert cat.search("destructible", "", limit=5000, tileset="L")[0]["model_ok"] in (True, False)
    grass = cat.get("doodad", "LSga", ["dfil"])["model"]
    assert grass["files"] == grass["missing"] == [r"Doodads\LordaeronSummer\Plants\SummerGrass\SummerGrass0.mdl",
                                                  r"Doodads\LordaeronSummer\Plants\SummerGrass\SummerGrass1.mdl"]
    assert cat.get("unit", "hfoo", ["umdl"])["model"]["missing"] == []
    assert cat.model_paths("Doodads\\X\\Tree", 3, 2) == ["Doodads\\X\\Tree2.mdl"]
    assert cat.model_paths("Doodads\\X\\Rock.mdl", 1) == ["Doodads\\X\\Rock.mdl"]
    with pytest.raises(ToolError) as e:
        cat.search("unit", "", tileset="A")
    assert e.value.code == "bad_value"


def test_models_must_load_in_classic_graphics(cat):
    # the World Editor draws classic (SD) models: some HD files have no classic copy
    shrub3 = r"Doodads\Ruins\Plants\Ruins_Shrub\Ruins_Shrub3.mdl"
    assert cat.model_exists(shrub3, hd=True) and not cat.model_exists(shrub3)
    assert cat.get("doodad", "ZPsh", ["dfil"])["model"]["missing"] == [shrub3]
    row = next(r for r in cat.search("doodad", "", limit=5000) if r["id"] == "ZPsh")
    assert row["model_ok"] is False and row["variations_ok"] == [0, 1, 2]
    assert cat.missing_models("doodad", "ZPsh", 1)[1] == []
    assert cat.get("doodad", "LCss", ["dfil"])["model"]["missing"] == [
        r"Doodads\LordaeronCapital\Props\Statues\Lordaeron_Statue_Sword.mdl"]
    assert "variations_ok" not in next(r for r in cat.search("doodad", "Grass Patch") if r["id"] == "LPgp")
