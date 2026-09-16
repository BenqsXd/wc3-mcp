import pytest

from corpus import _storage, ladder_maps, open_sample, sample_map_ids
from wc3mcp.errors import ToolError
from wc3mcp.formats import objmods
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.objdata import objdata_edit, objdata_get, objdata_list, var_type
from wc3mcp.ops.strings import load_strings
from wc3mcp.project.workspace import MapProject

WARCHASERS = "casc:Maps/Scenario/(4)WarChasers.w3m"
pytestmark = pytest.mark.skipif(WARCHASERS not in sample_map_ids() or not ladder_maps(),
                                reason="needs the Warcraft III install and ladder maps")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)  # base data: stable values


@pytest.fixture
def project(tmp_path):
    src = tmp_path / "WarChasers.w3m"
    src.write_bytes(open_sample(WARCHASERS).data)
    return MapProject.open(src)


@pytest.fixture
def plain_project(tmp_path):
    src = tmp_path / ladder_maps()[0].name
    src.write_bytes(ladder_maps()[0].read_bytes())
    return MapProject.open(src)


def test_var_type_rules():
    assert [var_type(t) for t in ("real", "unreal", "bool", "silenceFlags", "attackType", "modelList")] == [1, 2, 0, 0, 3, 3]


def test_list_includes_custom_and_modified_objects(project, catalog):
    units = {o["id"]: o for o in objdata_list(project, catalog, "unit")["objects"]}
    assert units["nC01"] == {"id": "nC01", "base": "negf", "custom": True, "modifications": 9,
                             "name": "juggernaut tower"}
    assert units["nzep"]["custom"] is False and units["nzep"]["modifications"] == 5
    assert all(o["custom"] for o in objdata_list(project, catalog, "unit", custom_only=True)["objects"])
    items = {o["id"]: o for o in objdata_list(project, catalog, "item")["objects"]}
    assert items["IC17"]["name"] == "Ankh of Reincarnation Deluxe"


def test_get_merges_main_and_skin_over_base(project, catalog):
    doc = objdata_get(project, catalog, "unit", "nC01")
    assert (doc["base"], doc["custom"], doc["name"]) == ("negf", True, "juggernaut tower")
    assert doc["fields"]["uacq"]["value"] == 1200.0 and doc["fields"]["uacq"]["modified"] is True
    assert doc["fields"]["unam"]["value"] == "juggernaut tower"
    assert any(f["modified"] is False for f in doc["fields"].values())
    assert objdata_get(project, catalog, "item", "IC17", fields=["igol"])["fields"]["igol"]["value"] == 5000


def test_get_unmodified_objects_have_typed_base_values(plain_project, catalog):
    unit = objdata_get(plain_project, catalog, "unit", "hfoo", fields=["uhpm"])
    assert unit["custom"] is False and unit["name"] == "Footman"
    assert unit["fields"]["uhpm"]["value"] == 420 and unit["fields"]["uhpm"]["modified"] is False
    ability = objdata_get(plain_project, catalog, "ability", "AHbz", fields=["Hbz1"])
    assert ability["fields"]["Hbz1"]["values"] == [6, 8, 10] and ability["fields"]["Hbz1"]["modified"] == []


def test_unknown_kind_and_object(project, catalog):
    with pytest.raises(ToolError) as e:
        objdata_list(project, catalog, "hero")
    assert e.value.code == "bad_kind"
    with pytest.raises(ToolError) as e:
        objdata_get(project, catalog, "unit", "zzzz")
    assert e.value.code == "not_found"


def test_create_custom_unit_writes_main_and_skin_files(plain_project, catalog):
    result = objdata_edit(plain_project, catalog, "unit", [
        {"op": "create", "base": "hfoo", "set": {"Name": "Arena Guard", "HP": 777}}])
    assert result == {"changed": True, "created": ["h000"], "warnings": []}
    main = objmods.parse(plain_project.read("war3map.w3u"), False)
    skin = objmods.parse(plain_project.read("war3mapSkin.w3u"), False)
    assert [(e.base_id, e.new_id) for e in main.custom] == [(b"hfoo", b"h000")]
    assert [(e.base_id, e.new_id) for e in skin.custom] == [(b"hfoo", b"h000")]
    assert [(m.id, m.value, m.end) for m in main.custom[0].mods] == [(b"uhpm", 777, objmods.ZERO_ID)]
    assert [(m.id, m.value) for m in skin.custom[0].mods] == [(b"unam", "Arena Guard")]
    doc = objdata_get(plain_project, catalog, "unit", "h000", fields=["uhpm", "unam"])
    assert doc["custom"] and doc["name"] == "Arena Guard" and doc["fields"]["uhpm"]["value"] == 777


def test_create_ability_with_level_values(plain_project, catalog):
    result = objdata_edit(plain_project, catalog, "ability", [
        {"op": "create", "base": "AHbz", "set": {"Hbz1": {"1": 7, "3": 12}}}])
    assert result["created"] == ["A000"]
    mods = objmods.parse(plain_project.read("war3map.w3a"), True).custom[0].mods
    assert [(m.id, m.level, m.pointer, m.value) for m in mods] == [(b"Hbz1", 1, 1, 7), (b"Hbz1", 3, 1, 12)]
    doc = objdata_get(plain_project, catalog, "ability", "A000", fields=["Hbz1"])
    assert doc["fields"]["Hbz1"]["values"] == [7, 8, 12] and doc["fields"]["Hbz1"]["modified"] == [1, 3]


def test_modify_reset_and_delete(project, catalog):
    objdata_edit(project, catalog, "unit", [{"op": "set", "id": "nzep", "set": {"uhpm": 999}}])
    assert objdata_get(project, catalog, "unit", "nzep", fields=["uhpm"])["fields"]["uhpm"]["value"] == 999
    objdata_edit(project, catalog, "unit", [{"op": "reset", "id": "nzep", "fields": ["uhpm"]}])
    assert objdata_get(project, catalog, "unit", "nzep", fields=["uhpm"])["fields"]["uhpm"]["modified"] is False
    objdata_edit(project, catalog, "unit", [{"op": "delete", "id": "nC01"}])
    assert "nC01" not in {o["id"] for o in objdata_list(project, catalog, "unit")["objects"]}


def test_updating_an_existing_modification_keeps_its_record(project, catalog):
    def uhpm_mod():
        main = objmods.parse(project.read("war3map.w3u"), False)
        return next(m for e in main.original if e.base_id == b"hmtt" for m in e.mods if m.id == b"uhpm")

    before = uhpm_mod()
    objdata_edit(project, catalog, "unit", [{"op": "set", "id": "hmtt", "set": {"uhpm": 1100}}])
    after = uhpm_mod()
    assert after.value == 1100 and after.end == before.end


def test_setting_trigstr_backed_text_updates_the_string_table(plain_project, catalog):
    objdata_edit(plain_project, catalog, "unit", [{"op": "create", "base": "hfoo", "set": {"Name": "placeholder"}}])
    skin = objmods.parse(plain_project.read("war3mapSkin.w3u"), False)
    skin.custom[0].mods[0].value = "TRIGSTR_900"
    plain_project.write("war3mapSkin.w3u", objmods.serialize(skin))
    strings = load_strings(plain_project)
    strings.set(900, "Old Name")
    plain_project.write("war3map.wts", strings.serialize())
    assert objdata_get(plain_project, catalog, "unit", "h000")["name"] == "Old Name"
    objdata_edit(plain_project, catalog, "unit", [{"op": "set", "id": "h000", "set": {"Name": "New Name"}}])
    assert load_strings(plain_project).get(900) == "New Name"
    assert objmods.parse(plain_project.read("war3mapSkin.w3u"), False).custom[0].mods[0].value == "TRIGSTR_900"


@pytest.mark.parametrize("op, code", [
    ({"op": "create", "base": "zzzz"}, "not_found"),
    ({"op": "create", "base": "hfoo", "id": "hfoo"}, "id_taken"),
    ({"op": "create", "base": "hfoo", "id": "toolong"}, "bad_value"),
    ({"op": "set", "id": "hfoo", "set": {"no such field": 1}}, "unknown_field"),
    ({"op": "set", "id": "hfoo", "set": {"uhpm": "many"}}, "bad_value"),
    ({"op": "set", "id": "hfoo", "set": {"uhpm": {"1": 5}}}, "bad_value"),
    ({"op": "set", "id": "zzzz", "set": {"uhpm": 5}}, "not_found"),
    ({"op": "explode", "id": "hfoo"}, "bad_op"),
    ({"op": "create", "base": "hfoo", "fields": {"uhpm": 5}}, "bad_op"),   # "set" misspelt
])
def test_edit_errors(plain_project, catalog, op, code):
    with pytest.raises(ToolError) as e:
        objdata_edit(plain_project, catalog, "unit", [op])
    assert e.value.code == code and e.value.details["op_index"] == 0


def test_ambiguous_field_and_atomic_batch(plain_project, catalog):
    with pytest.raises(ToolError) as e:
        objdata_edit(plain_project, catalog, "ability", [
            {"op": "create", "base": "AHbz", "set": {"Hbz1": {"1": 7}}},
            {"op": "set", "id": "AHbz", "set": {"Data": {"1": 1}}}])
    assert e.value.code == "ambiguous_field" and e.value.details["op_index"] == 1
    assert plain_project.status()["dirty"] == []
