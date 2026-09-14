import pytest

from corpus import _storage, ladder_maps, open_sample, sample_map_ids
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.objdata import objdata_get, objdata_list, var_type
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
