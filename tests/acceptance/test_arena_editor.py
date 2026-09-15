"""Phase 6 acceptance in the World Editor: every hero-arena map opens and saves without errors and keeps what the tools
built; the campaign opens and saves in the Campaign Editor (pytest -m editor)."""
import pytest
import win32con
import win32gui

from arena import VARIANTS, build, check_campaign, check_map
from desktop.test_world_live import assert_script_build_keeps
from wc3mcp.desktop import editor as ed


@pytest.mark.editor
def test_arena_opens_and_saves_in_the_world_editor(tmp_path):
    editor = ed.Editor()
    if editor.status()["running"]:
        pytest.skip("a World Editor is already running")
    project = build(tmp_path / "arena")
    try:
        for variant in VARIANTS:
            path = project["maps"][variant]["path"]
            status = editor.open(path) if editor.status()["running"] else editor.launch(path)
            assert status["map"] == str(path) and status["dialogs"] == [], (variant, status)
            saved = editor.save()
            assert saved["saved"] and saved["errors"] == [], (variant, saved)
            # a new editor log per launch; it names every model or texture it could not load
            failures = [line for line in editor.log(100000)["log"] if "war3mapImported" in line]
            assert failures == [], (variant, failures)
            # the editor's own script for what the tools built is the one script_build writes
            assert_script_build_keeps(tmp_path, path, "war3map.lua" if variant == "lua" else "war3map.j")
        status = editor.open(project["campaign"])
        assert status["campaign"].endswith("/HeroArena.w3n") and status["dialogs"] == [], status
        saved = editor.save_campaign()
        assert saved["saved"] and saved["warnings"] == [], saved
    finally:
        if editor.status()["running"]:   # the editor reopens the modules left open at exit: leave it as it was
            for title in editor.status()["modules"]:
                if title.startswith("Campaign Editor"):
                    win32gui.PostMessage(editor.find_window(title), win32con.WM_CLOSE, 0, 0)
            editor.quit(discard=True)
    for variant in VARIANTS:
        check_map(project["maps"][variant], variant)
    check_campaign(project["campaign"])
