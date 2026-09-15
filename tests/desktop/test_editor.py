import shutil
import time
from pathlib import Path

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


def test_campaign_titles():
    m = ed.CAMPAIGN_TITLE.match("Campaign Editor - [C:/.../Campaigns/My Saga.w3n *]")
    assert (m["doc"], bool(m["dirty"])) == ("C:/.../Campaigns/My Saga.w3n", True)
    s = {"map": None, "dirty": False, "campaign": m["doc"], "campaign_dirty": True}
    assert ed._shows(s, Path(r"D:\Maps\Campaigns\My Saga.w3n")) and not ed._shows(s, Path(r"D:\Maps\Saga.w3n"))
    assert ed._unsaved(s) == "the campaign C:/.../Campaigns/My Saga.w3n"
    assert ed._unsaved({**s, "campaign_dirty": False}) is None


def test_dialog_act_refuses_disabled_controls(monkeypatch):
    clicked = []
    editor = ed.Editor()
    monkeypatch.setattr(editor, "find_window", lambda title: 1)
    monkeypatch.setattr(ed.win32gui, "GetClassName", lambda h: "#32770")
    monkeypatch.setattr(win, "controls", lambda h: [
        {"hwnd": 2, "class": "Button", "id": 20, "text": "&Imported File:", "visible": True, "enabled": False}])
    monkeypatch.setattr(win, "click", clicked.append)
    with pytest.raises(ToolError) as e:
        editor.dialog_act("Campaign Editor", [{"control": 20, "click": True}])
    assert e.value.code == "control_disabled" and clicked == []


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


@pytest.mark.editor
def test_editor_ui_access(maps):
    plain, _ = maps
    editor = ed.Editor()
    if editor.status()["running"]:
        pytest.skip("a World Editor is already running")
    try:
        editor.launch(plain)
        assert "File" in [m["label"] for m in editor.menu()]
        editor.invoke("Scenario/Map Description...")
        editor.wait_window("Map Properties")
        [props] = [d for d in editor.dialogs() if d["title"] == "Map Properties"]
        assert any(c["id"] == 14 for c in props["controls"])
        after = editor.dialog_act("Map Properties", [{"control": 14, "set_text": "UI Test"}, {"control": "OK", "click": True}])
        assert after["closed"] is True
        for _ in range(40):
            if editor.status()["dirty"]:
                break
            time.sleep(0.25)
        assert editor.status()["dirty"] is True
        with pytest.raises(ToolError) as e:
            editor.dialog_act("No Such Dialog", [])
        assert e.value.code == "no_dialog"

        editor.invoke("Module/Trigger Editor")
        editor.wait_window("Trigger Editor")
        assert editor.menu(window="Trigger Editor") and "Trigger Editor" in editor.status()["modules"]
        assert editor.screenshot()[:8] == b"\x89PNG\r\n\x1a\n"
        assert editor.screenshot("Trigger Editor", region=[0, 0, 120, 60])[:8] == b"\x89PNG\r\n\x1a\n"
        editor.input("Trigger Editor", [{"wait": 0.1}])
        assert set(editor.log(lines=20)) >= {"log", "crashes"}
    finally:
        editor.quit(discard=True)
