import pytest

from corpus import HAVE_INSTALL, ladder_maps
from wc3mcp.errors import ToolError
from wc3mcp.ops.text import strings_edit, strings_get
from wc3mcp.project.workspace import MapProject

pytestmark = pytest.mark.skipif(not HAVE_INSTALL or not ladder_maps(), reason="needs a map with a string table")


@pytest.fixture
def project(tmp_path):
    src = tmp_path / ladder_maps()[0].name
    src.write_bytes(ladder_maps()[0].read_bytes())
    return MapProject.open(src)


def test_strings_get_reads_the_table_and_who_points_at_it(project):
    doc = strings_get(project, used_by=True)
    assert doc["file"].endswith(".wts") and doc["total"] > 0
    assert all("id" in row and "text" in row for row in doc["strings"])
    assert any(row["used_by"] for row in doc["strings"])          # the map info or object data points at them
    first = doc["strings"][0]
    hit = strings_get(project, query=first["text"][:6])
    assert any(row["id"] == first["id"] for row in hit["strings"]) and hit["matched"] <= doc["total"]


def test_strings_edit_sets_adds_removes_and_renames_everywhere(project):
    start = strings_get(project)
    first = start["strings"][0]
    result = strings_edit(project, [{"op": "set", "id": first["id"], "text": "Ravaged Keep"}])
    assert result["changed"] and result["updated"] == [first["id"]] and result["warnings"]
    assert strings_get(project, query="Ravaged Keep")["matched"] == 1
    added = strings_edit(project, [{"op": "add", "text": "A new quest"}])
    [new_id] = added["added"]
    assert strings_get(project, query="A new quest")["strings"][0]["id"] == new_id
    renamed = strings_edit(project, [{"op": "replace", "find": "Ravaged", "with": "Sentry"}])
    assert first["id"] in renamed["updated"] and strings_get(project, query="Sentry Keep")["matched"] == 1
    imported = strings_edit(project, [{"op": "import", "entries": {str(new_id): "Eine neue Aufgabe"}}])
    assert imported["updated"] == [new_id]
    assert strings_get(project, query="Aufgabe")["strings"][0]["text"] == "Eine neue Aufgabe"
    gone = strings_edit(project, [{"op": "remove", "id": new_id}])
    assert gone["removed"] == [new_id] and strings_get(project, query="Aufgabe")["matched"] == 0


def test_strings_edit_refuses_what_it_cannot_do(project):
    total = strings_get(project)["total"]
    for ops, code in (([{"op": "nope"}], "bad_op"),
                      ([{"op": "set", "id": 1, "text": 5}], "bad_value"),
                      ([{"op": "set", "id": 1, "text": "x", "extra": 1}], "bad_op"),
                      ([{"op": "remove", "id": 999999}], "not_found"),
                      ([{"op": "replace", "find": "", "with": "x"}], "bad_value"),
                      ([{"op": "import", "entries": {}}], "bad_value"),
                      ([], "bad_op")):
        with pytest.raises(ToolError) as e:
            strings_edit(project, ops)
        assert e.value.code == code, ops
    assert strings_get(project)["total"] == total       # every refusal left the table alone
