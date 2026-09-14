import pytest

from corpus import ladder_maps, open_sample, sample_map_ids
from wc3mcp.errors import ToolError
from wc3mcp.formats import w3i
from wc3mcp.formats.wts import TriggerStrings
from wc3mcp.ops.info import SCRIPT_WARNING, from_json, info_edit, info_get, to_json
from wc3mcp.project.workspace import MapProject


@pytest.fixture
def project(tmp_path):
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    return MapProject.open(src)


def test_info_get_resolves_trigger_strings(project):
    info = info_get(project)
    assert info["format_version"] in w3i.WRITABLE_VERSIONS
    assert info["name_ref"].startswith("TRIGSTR_") and not info["name"].startswith("TRIGSTR_")
    assert info["players"][0]["controller"] in ("user", "computer")


def test_edit_text_updates_wts_and_keeps_reference(project):
    before = info_get(project)
    result = info_edit(project, [{"op": "set", "path": "name", "value": "Arena of Tests"}])
    assert result["changed"] and SCRIPT_WARNING not in result["warnings"]
    after = info_get(project)
    assert after["name"] == "Arena of Tests" and after["name_ref"] == before["name_ref"]
    assert w3i.parse(project.read("war3map.w3i")).name == before["name_ref"]


def test_structural_edit_warns_about_script(project):
    result = info_edit(project, [{"op": "set", "path": "flags.use_custom_forces", "value": True},
                                 {"op": "set", "path": "players[0].race", "value": "orc"}])
    assert SCRIPT_WARNING in result["warnings"]
    info = info_get(project)
    assert info["flags"]["use_custom_forces"] is True and info["players"][0]["race"] == "orc"


def test_invalid_value_changes_nothing(project):
    before = (project.read("war3map.w3i"), project.read("war3map.wts"))
    with pytest.raises(ToolError) as e:
        info_edit(project, [{"op": "set", "path": "name", "value": "x"},
                            {"op": "set", "path": "players[0].controller", "value": "alien"}])
    assert e.value.code == "bad_value" and e.value.details["path"] == "players[0].controller"
    assert (project.read("war3map.w3i"), project.read("war3map.wts")) == before


def test_format_version_is_read_only_and_empty_batch_is_a_no_op(project):
    with pytest.raises(ToolError) as e:
        info_edit(project, [{"op": "set", "path": "format_version", "value": 1}])
    assert e.value.details["path"] == "format_version"
    assert info_edit(project, []) == {"changed": False, "warnings": []}


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_json_roundtrip_is_byte_exact(map_id):
    arc = open_sample(map_id)
    data = arc.read("war3map.w3i")
    wts_data = arc.read("war3map.wts") or b""
    mi, strings = w3i.parse(data), TriggerStrings.parse(wts_data)
    assert w3i.serialize(from_json(to_json(mi, strings), strings, mi)) == data
    assert strings.serialize() == wts_data
