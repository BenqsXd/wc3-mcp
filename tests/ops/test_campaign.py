import base64
import shutil
from pathlib import Path

import pytest

from corpus import HAVE_INSTALL, _storage
from wc3mcp.errors import ToolError
from wc3mcp.formats import w3f
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.mpq.writer import write_archive
from wc3mcp.ops.campaign import campaign_edit, campaign_get, new_campaign
from wc3mcp.ops.imports import imports_edit
from wc3mcp.ops.newmap import new_map
from wc3mcp.ops.objdata import objdata_edit, objdata_get
from wc3mcp.ops.script import map_validate
from wc3mcp.project.workspace import MapProject

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
DATA = Path(__file__).parents[1] / "formats" / "data" / "campaign"


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance="Custom_V1")


@pytest.fixture
def chapters(tmp_path, catalog):
    paths = []
    for name in ("Chapter1", "Chapter2"):
        paths.append(tmp_path / f"{name}.w3x")
        new_map(paths[-1], catalog, width=32, height=32, players=1, name=name).close()
    return paths


def test_editor_campaign_view(tmp_path, catalog):
    shutil.copyfile(DATA / "Full.w3n", tmp_path / "Full.w3n")
    project = MapProject.open(tmp_path / "Full.w3n")
    doc = campaign_get(project, catalog)
    assert (doc["name"], doc["name_ref"], doc["difficulty"], doc["author"]) == ("Test Campaign", "TRIGSTR_001", "Hard", "Tests")
    assert doc["description"] == "Line one\nLine two" and doc["variable_difficulty"] is True
    assert doc["minimap"] == {"preset": "Undead"}
    assert doc["loading_screen"] == {
        "background": {"preset": 2, "name": "Orc"}, "background_version": "reforged",
        "ambient_sound": {"preset": 4, "name": "Night Elf"}, "cursor": "undead",
        "fog": {"style": "exponential_2", "z_start": 111.0, "z_end": 222.0, "density": 0.33, "height_start": 444.0,
                "height_end": 555.0, "linear_start": 666.0, "linear_end": 777.0, "max_opacity": 0.88,
                "color": {"r": 0, "g": 0, "b": 0, "a": 0}, "over_sky": True}}
    assert [(b["chapter"], b["title"], b["map"], b["visible"], b["cinematic"]) for b in doc["buttons"]] == [
        ("Prologue", "The Start", "Chapter One.w3x", True, False), ("Chapter Two", "Cinematic End", "Chapter Two.w3x", False, True)]
    assert [(m["name"], m["used"]) for m in doc["maps"]] == [("Chapter One.w3x", True), ("Chapter Two.w3x", True)]
    assert doc["imports"] == 1 and doc["object_data"] == {"unit": ["war3campaign.w3u", "war3campaignSkin.w3u"]}
    assert map_validate(project, catalog) == {"errors": [], "warnings": []}
    # the view written back changes nothing
    assert campaign_edit(project, catalog, [])["changed"] is False
    assert campaign_edit(project, catalog, [{"op": "set", "path": "name", "value": "Test Campaign"}])["changed"] is False
    assert objdata_get(project, catalog, "unit", "hpea", ["urun"])["fields"]["urun"]["value"] == 123.5


@pytest.mark.parametrize("sample", sorted(p.name for p in DATA.glob("*.w3f")))
def test_unchanged_view_keeps_every_editor_sample(tmp_path, catalog, sample):
    data = (DATA / sample).read_bytes()
    ci = w3f.parse(data)
    files = {"war3campaign.w3f": data}
    files.update({m.path: b"MPQ\x1a" for m in ci.maps})
    (tmp_path / "c.w3n").write_bytes(write_archive(files))
    project = MapProject.open(tmp_path / "c.w3n")
    doc = campaign_get(project, catalog)
    ops = [{"op": "set", "path": key, "value": doc[key]} for key in ("minimap", "loading_screen", "buttons")]
    assert campaign_edit(project, catalog, ops)["changed"] is False


def test_build_a_campaign(tmp_path, catalog, chapters):
    project = new_campaign(tmp_path / "Saga.w3n", catalog, name="Saga", author="Tests")
    assert campaign_get(project, catalog)["name"] == "Saga" and project.status()["dirty"] == []
    result = campaign_edit(project, catalog, [
        {"op": "add_map", "source": str(chapters[0])},
        {"op": "add_map", "source": str(chapters[1]), "name": "Finale.w3x"},
        {"op": "set", "path": "description", "value": "Two chapters"},
        {"op": "set", "path": "variable_difficulty", "value": True},
        {"op": "set", "path": "minimap", "value": {"map": "Chapter1.w3x"}},
        {"op": "set", "path": "loading_screen.background", "value": {"preset": "Loading - Human 01"}},
        {"op": "set", "path": "loading_screen.ambient_sound", "value": {"preset": "Human"}},
        {"op": "set", "path": "loading_screen.cursor", "value": "orc"},
        {"op": "set", "path": "loading_screen.fog", "value": {"style": "linear", "z_start": 500, "z_end": 3000,
                                                               "color": {"r": 10, "g": 20, "b": 30}}},
        {"op": "append", "path": "buttons", "value": {"chapter": "Chapter One", "title": "Arrival", "map": "Chapter1.w3x",
                                                      "visible": True}},
        {"op": "append", "path": "buttons", "value": {"chapter": "Finale", "title": "The End", "map": "finale.w3x",
                                                      "cinematic": True}}])
    assert result["warnings"] == []
    doc = campaign_get(project, catalog)
    assert doc["loading_screen"]["background"] == {"preset": 16, "name": "Loading - Human 01"}
    assert doc["loading_screen"]["fog"] == {"style": "linear", "z_start": 500.0, "z_end": 3000.0, "density": 0.0,
                                            "height_start": 0.0, "height_end": 0.0, "linear_start": 0.0,
                                            "linear_end": 0.0, "max_opacity": 0.0,
                                            "color": {"r": 10, "g": 20, "b": 30, "a": 255}, "over_sky": False}
    assert [b["map"] for b in doc["buttons"]] == ["Chapter1.w3x", "Finale.w3x"] and doc["buttons"][1]["cinematic"]
    assert [m["name"] for m in doc["maps"]] == ["Chapter1.w3x", "Finale.w3x"]
    ci = w3f.parse(project.read("war3campaign.w3f"))
    assert ci.flags == w3f.FLAG_VARIABLE_DIFFICULTY | w3f.FLAG_MINIMAP_FROM_MAP and ci.buttons[0].title.startswith("TRIGSTR_")
    assert project.read("Finale.w3x") == chapters[1].read_bytes()

    objdata_edit(project, catalog, "unit", [{"op": "set", "id": "hfoo", "set": {"unam": "Campaign Footman"}}])
    names = {f["name"] for f in project.list_files()}
    assert {"war3campaign.w3u", "war3campaign.wts"} <= names and "war3map.w3u" not in names
    imports_edit(project, [{"op": "add", "path": "war3campImported\\note.txt",
                            "content_base64": base64.b64encode(b"hello").decode()}])
    assert "war3campaign.imp" in {f["name"] for f in project.list_files()}
    assert map_validate(project, catalog) == {"errors": [], "warnings": []}
    project.save()
    project.close()

    reopened = MapProject.open(tmp_path / "Saga.w3n")
    assert campaign_get(reopened, catalog)["buttons"][0]["title"] == "Arrival"
    assert objdata_get(reopened, catalog, "unit", "hfoo", ["unam"])["fields"]["unam"]["value"] == "Campaign Footman"

    out = tmp_path / "out" / "Chapter1.w3x"
    assert campaign_edit(reopened, catalog, [{"op": "extract_map", "name": "chapter1.w3x", "dest": str(out)}])["extracted"]
    assert out.read_bytes() == chapters[0].read_bytes()


@pytest.mark.parametrize("op, code", [
    ({"op": "append", "path": "buttons", "value": {"title": "x", "map": "Nope.w3x"}}, "bad_value"),
    ({"op": "remove_map", "name": "Chapter1.w3x"}, "bad_value"),     # still used by a button
    ({"op": "add_map", "source": "C:/no/such/map.w3x"}, "not_found"),
    ({"op": "set", "path": "loading_screen.cursor", "value": "gnoll"}, "bad_value"),
    ({"op": "set", "path": "loading_screen.background", "value": {"preset": "Nowhere"}}, "bad_value"),
    ({"op": "set", "path": "maps", "value": []}, "bad_value"),
    ({"op": "extract_map", "name": "Chapter1.w3x", "dest": "{existing}"}, "exists"),
    ({"op": "explode"}, "bad_op"),
])
def test_edit_errors_are_atomic(tmp_path, catalog, chapters, op, code):
    project = new_campaign(tmp_path / "Atomic.w3n", catalog)
    campaign_edit(project, catalog, [{"op": "add_map", "source": str(chapters[0])},
                                     {"op": "append", "path": "buttons", "value": {"map": "Chapter1.w3x"}}])
    project.save()
    if op.get("dest") == "{existing}":
        op = {**op, "dest": str(chapters[1])}
    with pytest.raises(ToolError) as e:
        campaign_edit(project, catalog, [{"op": "set", "path": "name", "value": "Changed"}, op])
    assert e.value.code == code
    assert project.status()["dirty"] == [] and campaign_get(project, catalog)["name"] != "Changed"


def test_maps_are_not_campaigns(tmp_path, catalog, chapters):
    with pytest.raises(ToolError) as e:
        campaign_get(MapProject.open(chapters[0]), catalog)
    assert e.value.code == "not_a_campaign"
    with pytest.raises(ToolError) as e:
        new_campaign(chapters[0], catalog)
    assert e.value.code == "exists"
