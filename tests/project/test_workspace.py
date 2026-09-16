from pathlib import Path

import pytest

from corpus import ladder_maps
from wc3mcp.errors import ToolError
from wc3mcp.mpq.reader import Archive
from wc3mcp.mpq.writer import write_archive
from wc3mcp.project.workspace import MapProject


def make_map(path: Path, files: dict, **kw) -> Path:
    path.write_bytes(write_archive(files, **kw))
    return path


def test_open_edit_save_reopen(tmp_path):
    src = make_map(tmp_path / "m.w3x", {"war3map.w3i": b"info", "war3map.j": b"old"})
    original = src.read_bytes()
    p = MapProject.open(src)
    assert [f["name"] for f in p.list_files()] == ["war3map.j", "war3map.w3i"]
    p.write("war3map.j", b"new script")
    assert p.status()["dirty"] == ["war3map.j"]
    result = p.save()
    assert result["saved"] and Path(result["backup"]).read_bytes() == original
    p.close()
    assert Archive.open(src).read("war3map.j") == b"new script"


def test_reopen_resumes_unsaved_edits(tmp_path):
    src = make_map(tmp_path / "m.w3x", {"a.txt": b"1"})
    MapProject.open(src).write("a.txt", b"2")
    p = MapProject.open(src)
    assert p.read("a.txt") == b"2" and p.status()["dirty"] == ["a.txt"]


def test_save_refuses_when_source_changed(tmp_path):
    src = make_map(tmp_path / "m.w3x", {"a.txt": b"1"})
    p = MapProject.open(src)
    p.write("a.txt", b"mine")
    make_map(src, {"a.txt": b"theirs"})
    with pytest.raises(ToolError) as e:
        p.save()
    assert e.value.code == "source_changed"
    assert p.save(force=True)["saved"]
    assert Archive.open(src).read("a.txt") == b"mine"


def test_save_refuses_game_install(tmp_path, monkeypatch):
    install = tmp_path / "inst"
    install.mkdir()
    monkeypatch.setenv("WC3MCP_INSTALL", str(install))
    p = MapProject.open(make_map(install / "m.w3x", {"a.txt": b"1"}))
    p.write("a.txt", b"2")
    with pytest.raises(ToolError) as e:
        p.save()
    assert e.value.code == "install_read_only"


def test_close_requires_discard_for_unsaved(tmp_path):
    p = MapProject.open(make_map(tmp_path / "m.w3x", {"a.txt": b"1"}))
    p.delete("a.txt")
    with pytest.raises(ToolError) as e:
        p.close()
    assert e.value.code == "unsaved_changes"
    p.close(discard=True)


def test_bad_names_rejected(tmp_path):
    p = MapProject.open(make_map(tmp_path / "m.w3x", {"a.txt": b"1"}))
    for bad in ("..\\evil.txt", "C:\\x.txt", "\\abs.txt", "(listfile)", ""):
        with pytest.raises(ToolError):
            p.write(bad, b"x")


def test_snapshot_create_diff_restore(tmp_path):
    p = MapProject.open(make_map(tmp_path / "m.w3x", {"a.txt": b"1", "b.txt": b"2"}))
    p.snapshot("create", "before")
    p.write("a.txt", b"changed")
    p.write("c.txt", b"new")
    p.delete("b.txt")
    assert p.snapshot("diff", "before") == {"added": ["c.txt"], "removed": ["b.txt"], "changed": ["a.txt"]}
    p.snapshot("restore", "before")
    assert p.read("a.txt") == b"1" and p.read("b.txt") == b"2"
    assert p.snapshot("list")["snapshots"] == ["before"]


def test_folder_save_and_open(tmp_path):
    p = MapProject.open(make_map(tmp_path / "m.w3x", {"war3map.w3i": b"i", "war3mapImported\\x.blp": b"b"}))
    folder = tmp_path / "m_folder.w3x"
    assert p.save(dest=folder, format="folder")["saved"]
    q = MapProject.open(folder)
    assert q.status()["format"] == "folder" and q.read("war3mapImported\\x.blp") == b"b"


def test_protected_map_keeps_unnamed_files(tmp_path):
    src = make_map(tmp_path / "p.w3x", {"war3map.w3i": b"info", "secret\\x.txt": b"hidden" * 500}, listfile=False)
    p = MapProject.open(src)
    assert p.status()["protected"] and p.status()["unnamed_files"] == 1
    p.write("war3map.w3i", b"info2")
    p.save()
    arc = Archive.open(src)
    assert arc.read("secret\\x.txt") == b"hidden" * 500 and arc.read("war3map.w3i") == b"info2"
    with pytest.raises(ToolError) as e:
        p.save(dest=tmp_path / "p_folder", format="folder")
    assert e.value.code == "unnamed_files"


MAPS = ladder_maps()


@pytest.mark.skipif(not MAPS, reason="no ladder maps in Documents")
def test_ladder_map_edit_keeps_other_files(tmp_path):
    src = tmp_path / MAPS[0].name
    src.write_bytes(MAPS[0].read_bytes())
    before = Archive.open(src)
    originals = {n: before.read(n) for n in before.list() if not n.startswith("(")}
    p = MapProject.open(src)
    p.write("war3mapImported\\note.txt", b"hello")
    p.save()
    after = Archive.open(src)
    assert after.read("war3mapImported\\note.txt") == b"hello"
    assert {n: after.read(n) for n in originals} == originals


def test_save_reports_a_locked_file(tmp_path, monkeypatch):
    src = make_map(tmp_path / "locked.w3x", {"war3map.j": b"old"})
    p = MapProject.open(src)
    p.write("war3map.j", b"new")
    from wc3mcp.project import workspace

    monkeypatch.setattr(workspace.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError(5, "Access is denied")))
    with pytest.raises(ToolError) as e:
        p.save()
    assert e.value.code == "file_in_use" and "editor_map action=close" in e.value.hint
