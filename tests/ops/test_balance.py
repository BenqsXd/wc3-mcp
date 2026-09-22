import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.balance import balance_report
from wc3mcp.ops.objdata import objdata_edit
from wc3mcp.project.workspace import MapProject

pytestmark = pytest.mark.skipif(not HAVE_INSTALL or not ladder_maps(),
                                reason="needs the Warcraft III install and a map")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance="Custom_V1")


@pytest.fixture
def project(tmp_path):
    src = tmp_path / ladder_maps()[0].name
    src.write_bytes(ladder_maps()[0].read_bytes())
    return MapProject.open(src)


def test_a_unit_report_reads_damage_life_and_price(project, catalog):
    objdata_edit(project, catalog, "unit", [
        {"op": "create", "base": "hfoo", "id": "h001", "set": {"ua1d": 2, "ua1s": 6}},
        {"op": "create", "base": "hfoo", "id": "h002", "set": {"ua1d": 4, "ua1s": 6, "ugol": 60}}])
    doc = balance_report(project, catalog, "unit")
    rows = {row["id"]: row for row in doc["objects"]}
    assert set(rows) == {"h001", "h002"}
    plain, strong = rows["h001"], rows["h002"]
    # two more dice of six: seven more damage on average, and the same cooldown
    assert strong["attacks"]["attack1"]["average_damage"] == plain["attacks"]["attack1"]["average_damage"] + 7
    assert strong["damage_per_second"] > plain["damage_per_second"]
    assert plain["effective_life"] > plain["life"]                             # armour buys effective life
    assert plain["armour"] >= 0 and plain["gold"] > 0 and plain["damage_per_gold"] > 0
    assert "(base + dice * (sides + 1) / 2) / cooldown" in doc["formulas"]["damage_per_second"]
    assert "ua1c" in plain["read"]
    assert any("damage per gold" in flag for flag in strong["flags"])          # cheaper and stronger than the stock
    assert [s["id"] for s in plain["closest_stock"]][:1] == ["hfoo"]


def test_armour_follows_the_formula_and_a_free_unit_does_not_divide_by_zero(project, catalog):
    objdata_edit(project, catalog, "unit", [
        {"op": "create", "base": "hfoo", "id": "h003", "set": {"uhpm": 1000, "udef": 10}},
        {"op": "create", "base": "hfoo", "id": "h004", "set": {"ugol": 0, "ulum": 0}}])
    rows = {row["id"]: row for row in balance_report(project, catalog, "unit", ["h003", "h004"])["objects"]}
    assert rows["h003"]["effective_life"] == round(1000 / (1 - 0.06 * 10 / (1 + 0.06 * 10)))
    assert "damage_per_gold" not in rows["h004"] and rows["h004"]["gold"] == 0


def test_an_item_report_totals_the_bonuses_its_abilities_give(project, catalog):
    objdata_edit(project, catalog, "item", [{"op": "create", "base": "rst1", "id": "I001", "set": {"igol": 50}}])
    [row] = balance_report(project, catalog, "item", ["I001"])["objects"]
    assert row["abilities"] and row["bonuses"] and row["gold"] == 50
    assert sum(row["bonus_per_100_gold"].values()) > 0
    assert any(s["id"] == "rst1" for s in row["closest_stock"])


def test_an_ability_report_walks_the_levels(project, catalog):
    objdata_edit(project, catalog, "ability", [
        {"op": "create", "base": "AHbz", "id": "A001", "set": {"acdn": {"1": 10, "2": 8, "3": 6}}}])
    [row] = balance_report(project, catalog, "ability", ["A001"])["objects"]
    assert [level["level"] for level in row["levels"]] == [1, 2, 3]
    assert row["levels"][0]["cooldown"] == 10 and row["levels"][2]["cooldown"] == 6


def test_balance_report_refuses_what_it_cannot_read(project, catalog):
    with pytest.raises(ToolError) as e:
        balance_report(project, catalog, "doodad")
    assert e.value.code == "bad_kind"
    with pytest.raises(ToolError) as e:
        balance_report(project, catalog, "unit", ["zzzz"])
    assert e.value.code == "not_found"
    assert balance_report(project, catalog, "item")["objects"] == []           # nothing custom yet: no invented rows


def test_a_hero_is_read_through_its_attributes_and_set_beside_heroes(project, catalog):
    """Every hero's unit fields say life 100, mana 0 and damage 2: the attributes and the gameplay constants carry
    the rest, so a report that reads the fields alone compares heroes with Peasants (improvement 9a)."""
    from wc3mcp.ops.constants import constants_edit

    objdata_edit(project, catalog, "unit", [{"op": "create", "base": "Hpal", "id": "H001",
                                             "set": {"ustr": 40, "ustp": 4, "uagi": 15, "uint": 20, "ugol": 425}}])
    constants_edit(project, catalog, {"MaxHeroLevel": 25})
    row = next(r for r in balance_report(project, catalog, "unit", ["H001"])["objects"] if r["id"] == "H001")
    assert row["hero"]["level_cap"] == 25 and len(row["hero"]["levels"]) == 2
    first, top = row["hero"]["levels"]
    assert first["life"] == 100 + 40 * 25 and first["mana"] == 20 * 15   # StrHitPointBonus, IntManaBonus
    assert first["primary_attribute"] == "strength" and first["attack_damage_bonus"] == 40
    assert top["attributes"]["strength"] == 40 + 24 * 4 and top["life"] == 100 + 136 * 25
    assert row["life"] == first["life"] and row["damage_per_second"] == first["damage_per_second"]
    assert {s["id"] for s in row["closest_stock"]} <= {"Hamg", "Hmkg", "Hpal", "Hblm", "Obla", "Ofar", "Otch",
                                                       "Oshd", "Udea", "Udre", "Ulic", "Ucrl", "Ekee", "Emoo",
                                                       "Ewar", "Edem"}
    plain = next(r for r in balance_report(project, catalog, "unit", ["hfoo"])["objects"] if r["id"] == "hfoo")
    assert "hero" not in plain and plain["life"] == 420


def test_abilities_on_one_button_cell_are_listed(tmp_path):
    from corpus import _storage
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops.balance import balance_report
    from wc3mcp.ops.newmap import new_map
    from wc3mcp.ops.objdata import objdata_edit

    c = Catalog(_storage(), balance="Custom_V1")
    p = new_map(str(tmp_path / "B.w3x"), c, width=64, height=64, players=2)
    objdata_edit(p, c, "ability", [{"op": "create", "base": "ANcl", "id": "A000", "set": {"abpx": 1, "abpy": 2}},
                                   {"op": "create", "base": "ANcl", "id": "A001", "set": {"abpx": 1, "abpy": 2}},
                                   {"op": "create", "base": "ANcl", "id": "A002", "set": {"abpx": 2, "abpy": 2}}])
    doc = balance_report(p, c, "ability")
    assert doc["button_cells"] == {"1,2": ["A000", "A001"]}
