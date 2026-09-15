import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps, open_sample
from wc3mcp.errors import ToolError
from wc3mcp.formats import w3r, wtg
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.elements import elements_edit, elements_list
from wc3mcp.ops.triggers import _all_params, _load
from wc3mcp.project.workspace import MapProject

WARCHASERS = "casc:Maps/Scenario/(4)WarChasers.w3m"
HUMAN01 = "casc:Campaign/Reforged/ROC/Human01.w3x"
pytestmark = pytest.mark.skipif(not HAVE_INSTALL or not ladder_maps(),
                                reason="needs the Warcraft III install and ladder maps")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)


def _copy(tmp_path, name: str, data: bytes) -> MapProject:
    src = tmp_path / name
    src.write_bytes(data)
    return MapProject.open(src)


@pytest.fixture
def melee(tmp_path):
    return _copy(tmp_path, ladder_maps()[0].name, ladder_maps()[0].read_bytes())


@pytest.fixture
def warchasers(tmp_path):
    return _copy(tmp_path, "WarChasers.w3m", open_sample(WARCHASERS).data)


def _error(fn, *args) -> ToolError:
    with pytest.raises(ToolError) as e:
        fn(*args)
    return e.value


def test_lists_of_a_campaign_map(tmp_path):
    project = _copy(tmp_path, "Human01.w3x", open_sample(HUMAN01).data)
    regions = elements_list(project, "region")
    assert regions["version"] == 7 and regions["items"]
    r = regions["items"][0]
    assert set(r) == {"name", "script_name", "index", "left", "bottom", "right", "top", "weather", "ambient_sound",
                      "color"}
    assert r["script_name"].startswith("gg_rct_") and r["left"] <= r["right"] and r["bottom"] <= r["top"]
    cameras = elements_list(project, "camera")
    assert cameras["version"] == 3 and all("camera_type" in c and "z_absolute" in c for c in cameras["items"])
    sounds = elements_list(project, "sound")
    if sounds["items"]:
        s = sounds["items"][0]
        assert s["name"].startswith("gg_snd_") and {"path", "label", "is_3d", "looping", "dialogue"} <= set(s)


def test_region_create_modify_rename_delete(melee, catalog):
    original = melee.read("war3map.w3r")
    before = elements_list(melee, "region")["items"]
    result = elements_edit(melee, catalog, "region", [
        {"op": "upsert", "name": "Spawn Area", "left": -512, "bottom": -256.5, "right": 0, "top": 128,
         "weather": "RAlr", "color": {"r": 255, "g": 0, "b": 16}}])
    assert result["changed"] and result["created"] == ["Spawn Area"]
    created = elements_list(melee, "region")["items"][-1]
    assert created == {"name": "Spawn Area", "script_name": "gg_rct_Spawn_Area",
                       "index": max([r["index"] for r in before], default=-1) + 1, "left": -512.0,
                       "bottom": -256.5, "right": 0.0, "top": 128.0, "weather": "RAlr", "ambient_sound": None,
                       "color": {"r": 255, "g": 0, "b": 16}}
    elements_edit(melee, catalog, "region", [{"op": "upsert", "name": "Spawn Area", "top": 256, "weather": None,
                                              "new_name": "Boss Area"}])
    changed = elements_list(melee, "region")["items"][-1]
    assert (changed["name"], changed["script_name"], changed["top"], changed["weather"]) == (
        "Boss Area", "gg_rct_Boss_Area", 256.0, None)
    assert not elements_edit(melee, catalog, "region", [{"op": "upsert", "name": "Boss Area", "top": 256}])["changed"]
    elements_edit(melee, catalog, "region", [{"op": "delete", "name": "Boss Area"}])
    assert melee.read("war3map.w3r") == original


def test_region_errors_leave_the_map_untouched(melee, catalog):
    original = melee.read("war3map.w3r")
    bad_batches = {
        "bad_value": [
            [{"op": "upsert", "name": "A", "left": 0, "bottom": 0, "right": 10}],
            [{"op": "upsert", "name": "A", "left": 10, "bottom": 0, "right": 0, "top": 10}],
            [{"op": "upsert", "name": "A", "left": 0, "bottom": 0, "right": 1, "top": 1, "weather": "XXXX"}],
            [{"op": "upsert", "name": "A", "left": 0, "bottom": 0, "right": 1, "top": 1, "ambient_sound": "gg_snd_No"}],
            [{"op": "upsert", "name": "", "left": 0, "bottom": 0, "right": 1, "top": 1}],
        ],
        "name_taken": [[{"op": "upsert", "name": "Spawn Area", "left": 0, "bottom": 0, "right": 1, "top": 1},
                        {"op": "upsert", "name": "Spawn_Area", "left": 0, "bottom": 0, "right": 1, "top": 1}]],
        "not_found": [[{"op": "delete", "name": "Nope"}]],
        "bad_op": [[{"op": "rename", "name": "A"}], [{"op": "delete", "name": "A", "extra": 1}]],
    }
    for code, batches in bad_batches.items():
        for ops in batches:
            assert _error(elements_edit, melee, catalog, "region", ops).code == code, ops
    assert _error(elements_edit, melee, catalog, "unit", []).code == "bad_kind"
    assert _error(elements_list, melee, "unit").code == "bad_kind"
    assert melee.read("war3map.w3r") == original


def test_camera_defaults_and_edits(melee, catalog):
    elements_edit(melee, catalog, "camera", [{"op": "upsert", "name": "Intro", "x": 128, "y": -64}])
    cam = next(c for c in elements_list(melee, "camera")["items"] if c["name"] == "Intro")
    assert cam["script_name"] == "gg_cam_Intro"
    assert (cam["x"], cam["y"], cam["angle_of_attack"], cam["distance"], cam["field_of_view"], cam["far_z"]) == (
        128.0, -64.0, 304.0, 1650.0, 70.0, 5000.0)
    elements_edit(melee, catalog, "camera", [{"op": "upsert", "name": "Intro", "rotation": 45}])
    assert next(c for c in elements_list(melee, "camera")["items"] if c["name"] == "Intro")["rotation"] == 45.0
    version = elements_list(melee, "camera")["version"]
    if version < 3:
        assert _error(elements_edit, melee, catalog, "camera",
                      [{"op": "upsert", "name": "Intro", "camera_type": 1}]).code == "bad_value"
    assert _error(elements_edit, melee, catalog, "camera", [{"op": "upsert", "name": "New"}]).code == "bad_value"


def test_sound_with_label_and_dialogue(melee, catalog):
    result = elements_edit(melee, catalog, "sound", [
        {"op": "upsert", "name": "Hello", "path": "Units\\Human\\Footman\\FootmanYesAttack2.flac",
         "label": "FootmanYesAttack", "is_3d": True, "dialogue": {"text": "For the king!", "speaker": "Footman"}}])
    assert result["created"] == ["gg_snd_Hello"]
    [s] = [x for x in elements_list(melee, "sound")["items"] if x["name"] == "gg_snd_Hello"]
    assert (s["is_3d"], s["stop_when_out_of_range"], s["looping"], s["label"], s["pitch"]) == (
        True, True, False, "FootmanYesAttack", None)
    assert s["dialogue"]["text"] == "For the king!" and s["dialogue"]["speaker"] == "Footman"
    assert s["dialogue"]["text_ref"].startswith("TRIGSTR_")
    assert b"For the king!" in melee.read("war3map.wts")
    elements_edit(melee, catalog, "sound", [{"op": "upsert", "name": "gg_snd_Hello", "dialogue": None, "pitch": 1.5}])
    [s] = [x for x in elements_list(melee, "sound")["items"] if x["name"] == "gg_snd_Hello"]
    assert s["dialogue"] is None and s["pitch"] == 1.5
    for op in ({"op": "upsert", "name": "Bad Name", "path": "Units\\Human\\Footman\\FootmanYesAttack2.flac"},
               {"op": "upsert", "name": "Other", "path": "Nope\\Missing.flac"},
               {"op": "upsert", "name": "Other", "path": "Units\\Human\\Footman\\FootmanYesAttack2.flac",
                "label": "NoSuchLabel"},
               {"op": "upsert", "name": "Other"}):
        assert _error(elements_edit, melee, catalog, "sound", [op]).code == "bad_value", op
    elements_edit(melee, catalog, "region", [{"op": "upsert", "name": "Pond", "left": 0, "bottom": 0, "right": 64,
                                              "top": 64, "ambient_sound": "gg_snd_Hello"}])
    assert _error(elements_edit, melee, catalog, "sound", [{"op": "delete", "name": "Hello"}]).code == "in_use"


def test_referenced_region_rename_updates_triggers(warchasers, catalog):
    def referenced():
        tf, _ = _load(warchasers, catalog.trigger_data)
        return {p.value for t in tf.elements if isinstance(t, wtg.Trigger) for p in _all_params(t.ecas)
                if p.type == wtg.VARIABLE and p.value.startswith("gg_rct_")}

    region = next(r for r in elements_list(warchasers, "region")["items"] if r["script_name"] in referenced())
    error = _error(elements_edit, warchasers, catalog, "region", [{"op": "delete", "name": region["name"]}])
    assert error.code == "in_use" and error.details["triggers"]
    elements_edit(warchasers, catalog, "region", [{"op": "upsert", "name": region["name"],
                                                   "new_name": "Renamed By Test"}])
    names = referenced()
    assert "gg_rct_Renamed_By_Test" in names and region["script_name"] not in names
    assert "Renamed By Test" in [g.name for g in w3r.parse(warchasers.read("war3map.w3r")).regions]
