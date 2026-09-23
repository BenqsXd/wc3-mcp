"""Per-level values (a line, a list, a tooltip template), the write-time warnings and the map's object counts."""
import pytest

from corpus import HAVE_INSTALL, _storage
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.newmap import new_map
from wc3mcp.ops.objdata import objdata_edit, objdata_get

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)


def test_levels_come_from_a_line_a_list_and_a_template(tmp_path, catalog):
    p = new_map(str(tmp_path / "L.w3x"), catalog, width=64, height=64, players=2)
    objdata_edit(p, catalog, "ability", [{"op": "create", "base": "AHtb", "id": "A000", "set": {
        "alev": 10,
        "acdn": {"from": 12, "step": -0.5},
        "amcs": [75, 80, 85, 90, 95, 100, 105, 110, 115, 120],
        "Htb1": {"from": 100, "to": 550},
        "atp1": {"template": "Storm Bolt [{level}] - {Htb1} damage, {acdn} s"}}}])
    f = objdata_get(p, catalog, "ability", "A000", ["acdn", "amcs", "Htb1", "atp1"])["fields"]
    assert f["acdn"]["values"] == [12, 11.5, 11, 10.5, 10, 9.5, 9, 8.5, 8, 7.5]
    assert f["amcs"]["values"][-1] == 120 and f["Htb1"]["values"][-1] == 550
    assert f["atp1"]["values"][0] == "Storm Bolt [1] - 100 damage, 12 s"
    assert f["atp1"]["values"][9] == "Storm Bolt [10] - 550 damage, 7.5 s"


def test_a_template_naming_an_unknown_field_is_refused(tmp_path, catalog):
    from wc3mcp.errors import ToolError

    p = new_map(str(tmp_path / "T.w3x"), catalog, width=64, height=64, players=2)
    with pytest.raises(ToolError) as e:
        objdata_edit(p, catalog, "ability", [{"op": "create", "base": "AHtb", "id": "A000",
                                              "set": {"atp1": {"template": "{nope}"}}}])
    assert e.value.code == "bad_value" and "nope" in e.value.message


def test_hero_copies_warn_about_a_lowercase_id_and_more_than_five_hero_abilities(tmp_path, catalog):
    p = new_map(str(tmp_path / "H.w3x"), catalog, width=64, height=64, players=2)
    auto = objdata_edit(p, catalog, "unit", [{"op": "create", "base": "Hmkg"}])
    assert auto["created"] == ["H000"] and auto["warnings"] == []
    out = objdata_edit(p, catalog, "unit", [{"op": "create", "base": "Hmkg", "id": "h000",
                                             "set": {"uhab": "AHtb,AHtc,AHbh,AHav,AHhb,AHds"}}])
    assert any("h000" in w and "capital" in w for w in out["warnings"])
    assert any("uhab" in w and "5" in w for w in out["warnings"])


def test_isit_zero_names_the_unlimited_shape(tmp_path, catalog):
    from wc3mcp.errors import ToolError

    p = new_map(str(tmp_path / "I.w3x"), catalog, width=64, height=64, players=2)
    with pytest.raises(ToolError) as e:
        objdata_edit(p, catalog, "item", [{"op": "set", "id": "rst1", "set": {"isit": 0}}])
    assert "isto 3, isit 3" in (e.value.hint or "") and "never in stock" in e.value.hint
    # the old hint recommended isto 0 as "unlimited": that makes the item unbuyable, so it warns now
    out = objdata_edit(p, catalog, "item", [{"op": "set", "id": "rst1", "set": {"isto": 0}}])
    assert any("never in stock" in w for w in out["warnings"])


def test_object_counts_per_kind(tmp_path, catalog):
    from wc3mcp.ops.objdata import object_counts

    p = new_map(str(tmp_path / "O.w3x"), catalog, width=64, height=64, players=2)
    objdata_edit(p, catalog, "unit", [{"op": "create", "base": "hfoo"},
                                      {"op": "set", "id": "hpea", "set": {"uhpm": 300}}])
    assert object_counts(p)["unit"] == {"custom": 1, "modified": 1}
