import shutil
import time

import pytest

from corpus import _storage, ladder_maps, open_sample
from wc3mcp.desktop import editor as ed
from wc3mcp.desktop import win
from wc3mcp.errors import ToolError


def test_parse_title():
    assert ed.parse_title("Warcraft III World Editor") == {"map": None, "untitled": False, "dirty": False}
    assert ed.parse_title("Warcraft III World Editor - [Untitled]") == {"map": None, "untitled": True, "dirty": False}
    assert ed.parse_title("Warcraft III World Editor - [Untitled *]") == {"map": None, "untitled": True, "dirty": True}
    assert ed.parse_title("Warcraft III World Editor - [C:/Maps/My Map.w3x]") == {
        "map": r"C:\Maps\My Map.w3x", "untitled": False, "dirty": False}
    assert ed.parse_title("Warcraft III World Editor - [C:/Maps/My Map.w3x *]")["dirty"] is True
    assert ed.parse_title("Notepad") is None


@pytest.fixture
def maps(tmp_path):
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops.script import script_build
    from wc3mcp.ops.triggers import triggers_edit
    from wc3mcp.project.workspace import MapProject

    jass = next(p for p in ladder_maps() if open_sample("ladder:" + p.name).read("war3map.j") is not None)
    plain, broken = tmp_path / "Plain Map.w3x", tmp_path / "Broken Map.w3x"
    shutil.copyfile(jass, plain)
    shutil.copyfile(jass, broken)
    catalog = Catalog(_storage())
    project = MapProject.open(broken)
    triggers_edit(project, catalog, [{"op": "trigger", "name": "Broken", "actions": [
        {"fn": "CustomScriptCode", "args": ["call UndefinedThing()"]}]}])
    script_build(project, catalog)
    project.save()
    project.close()
    return plain, broken


def rename_map(editor, name):
    main = editor.main()
    win.post_command(main, win.find_command(win.window_menu(main), "Scenario/Map Description..."))
    dialog = editor.wait_window("Map Properties")
    controls = win.controls(dialog)
    win.set_text(next(c["hwnd"] for c in controls if c["id"] == 14), name)
    win.click(next(c["hwnd"] for c in controls if c["id"] == 10))
    for _ in range(40):
        if editor.status()["dirty"]:
            return
        time.sleep(0.25)
    raise AssertionError("renaming did not mark the map dirty")


@pytest.mark.editor
def test_editor_lifecycle(maps):
    plain, broken = maps
    editor = ed.Editor()
    if editor.status()["running"]:
        pytest.skip("a World Editor is already running")
    try:
        status = editor.launch(plain)
        assert (status["map"], status["dirty"], status["launched_by_server"]) == (str(plain), False, True)
        with pytest.raises(ToolError) as e:
            editor.launch()
        assert e.value.code == "editor_running"

        rename_map(editor, "Renamed by test")
        with pytest.raises(ToolError) as e:
            editor.close()
        assert e.value.code == "unsaved_changes"
        with pytest.raises(ToolError) as e:
            editor.open(broken)
        assert e.value.code == "unsaved_changes"
        saved = editor.save()
        assert saved["saved"] and saved["errors"] == [] and editor.status()["dirty"] is False

        assert editor.open(broken)["map"] == str(broken)
        result = editor.compile()
        assert result["saved"] is False and result["disabled_triggers"] == ["Broken"]
        assert [e["trigger"] for e in result["errors"]] == ["Broken"]
        assert "UndefinedThing" in result["errors"][0]["message"]
        assert editor.status()["dirty"] is True and editor.status()["dialogs"] == []
        editor.close(discard=True)
        assert editor.status()["map"] is None
    finally:
        editor.quit(discard=True)
    assert editor.status()["running"] is False
