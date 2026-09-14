import base64

import pytest

from wc3mcp.errors import ToolError
from wc3mcp.formats import imp
from wc3mcp.mpq.writer import write_archive
from wc3mcp.ops.imports import imports_edit, imports_list
from wc3mcp.project.workspace import MapProject


def make_project(tmp_path, files) -> MapProject:
    src = tmp_path / "m.w3x"
    src.write_bytes(write_archive(files))
    return MapProject.open(src)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_add_from_source_and_base64(tmp_path):
    p = make_project(tmp_path, {"war3map.w3i": b"i"})
    icon = tmp_path / "icon.blp"
    icon.write_bytes(b"BLP1data")
    result = imports_edit(p, [{"op": "add", "path": "war3mapImported\\icon.blp", "source": str(icon)},
                              {"op": "add", "path": "war3mapImported/sound.mp3", "content_base64": b64(b"ID3")}])
    assert result["imports"] == [{"path": "war3mapImported/icon.blp", "flag": 29, "size": 8},
                                 {"path": "war3mapImported/sound.mp3", "flag": 29, "size": 3}]
    assert p.read("war3mapImported\\sound.mp3") == b"ID3"
    assert imp.parse(p.read("war3map.imp")).entries[0].path == "war3mapImported/icon.blp"


def test_replace_keeps_flag_and_remove_deletes_file(tmp_path):
    existing = imp.serialize(imp.ImportList(1, [imp.ImportEntry(13, "war3mapImported/a.txt")]))
    p = make_project(tmp_path, {"war3map.imp": existing, "war3mapImported\\a.txt": b"old"})
    imports_edit(p, [{"op": "add", "path": "war3mapImported/a.txt", "content_base64": b64(b"new")}])
    assert imports_list(p) == [{"path": "war3mapImported/a.txt", "flag": 13, "size": 3}]
    imports_edit(p, [{"op": "remove", "path": "war3mapImported/a.txt"}])
    assert imports_list(p) == []
    assert "war3mapImported\\a.txt" not in {f["name"] for f in p.list_files()}


def test_batch_is_atomic(tmp_path):
    p = make_project(tmp_path, {"war3map.w3i": b"i"})
    with pytest.raises(ToolError) as e:
        imports_edit(p, [{"op": "add", "path": "war3mapImported/x.txt", "content_base64": b64(b"x")},
                         {"op": "remove", "path": "war3mapImported/missing.txt"}])
    assert e.value.code == "no_such_import" and e.value.details["op_index"] == 1
    assert p.status()["dirty"] == []


@pytest.mark.parametrize("op, code", [
    ({"op": "add", "path": "..\\evil.txt", "content_base64": "eA=="}, "bad_name"),
    ({"op": "add", "path": "a.txt"}, "bad_op"),
    ({"op": "add", "path": "a.txt", "content_base64": "not base64!"}, "bad_content"),
    ({"op": "add", "path": "a.txt", "source": "C:/definitely/missing/file.bin"}, "not_found"),
    ({"op": "rename", "path": "a.txt"}, "bad_op"),
    ({"op": "add"}, "bad_op"),
])
def test_rejects_bad_ops(tmp_path, op, code):
    p = make_project(tmp_path, {"war3map.w3i": b"i"})
    with pytest.raises(ToolError) as e:
        imports_edit(p, [op])
    assert e.value.code == code and e.value.details["op_index"] == 0
