import shutil

import pytest

from corpus import _storage, ladder_maps, open_sample
from wc3mcp.desktop import game

PRELOAD = ('function PreloadFiles takes nothing returns nothing\n\n\tcall PreloadStart()\n'
           '\tcall Preload( "wc3mcp-probe-ok" )\n\tcall Preload( "second line" )\n\tcall PreloadEnd( 0.0 )\n\nendfunction\n')


def test_parse_preload():
    assert game.parse_preload(PRELOAD) == ["wc3mcp-probe-ok", "second line"]
    assert game.parse_preload("") == []


def test_interesting_log_lines():
    lines = ["9/15 08:52:52.967  GameMain Started",
             "9/15 08:52:55.802  Opening map - C:/Maps/x.w3x",
             "9/15 08:52:55.802  Opening mod - C:/Maps/x.w3x",
             "9/15 08:52:54.306  prism: Info: vendorId: NVIDIA",
             "9/15 08:53:03.032  [CLoginCallbacks] LoginDoorClose called"]
    assert game.interesting(lines) == [lines[0], lines[4]]


@pytest.mark.game
def test_game_run_returns_preload_results(tmp_path):
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops.script import script_build
    from wc3mcp.ops.triggers import triggers_edit
    from wc3mcp.project.workspace import MapProject

    jass = next(p for p in ladder_maps() if open_sample("ladder:" + p.name).read("war3map.j") is not None)
    target = tmp_path / "Game Test.w3x"
    shutil.copyfile(jass, target)
    catalog = Catalog(_storage())
    project = MapProject.open(target)
    lines = ["call PreloadGenClear()", "call PreloadGenStart()", 'call Preload("wc3mcp-game-test")',
             'call PreloadGenEnd("wc3mcp\\\\game_test.txt")']
    triggers_edit(project, catalog, [{"op": "trigger", "name": "Report", "events": [{"fn": "MapInitializationEvent"}],
                                      "actions": [{"fn": "CustomScriptCode", "args": [line]} for line in lines]}])
    script_build(project, catalog)
    project.save()
    project.close()

    runner = game.Game()
    result = runner.test(target, results=["wc3mcp\\game_test.txt"], timeout=240)
    assert result["results"] == {"wc3mcp\\game_test.txt": ["wc3mcp-game-test"]} and result["missing"] == []
    assert result["closed"] and runner.status()["running"] is False
    assert any("GameMain Started" in line for line in result["log"])


def test_benign_log_lines_are_separated():
    lines = ["9/15 08:52:52.967  GameMain Started",
             r"9/15 08:52:55.802  SysMsg: Could not load file: Doodads\x\y.mdl",
             r"9/15 08:52:55.802  model creation failed - Doodads\x\y.mdl",
             "9/15 08:53:03.032  [CLoginCallbacks] LoginDoorClose called",
             r"9/15 08:53:04.000  SysMsg: Could not load file: Doodads\x\y.mdl"]
    keep, benign, missing = game.split_log(lines)
    assert keep == [lines[0], lines[3]] and benign == [lines[2]] and missing == [r"Doodads\x\y.mdl"]


def test_screenshot_only_captures_a_game_window(monkeypatch):
    runner = game.Game()
    monkeypatch.setattr(game.win, "processes", lambda name: [])
    monkeypatch.setattr(game.win, "windows", lambda pid: [])
    assert runner._screenshot(1234) == (None, "no_game_window")
    monkeypatch.setattr(game.win, "windows", lambda pid: [7] if pid == 1234 else [])
    monkeypatch.setattr(game.win32gui, "GetWindowText", lambda h: "Warcraft III")
    monkeypatch.setattr(game.win, "activate", lambda h: None)
    monkeypatch.setattr(game.win32gui, "GetForegroundWindow", lambda: 99)   # something else took the foreground
    monkeypatch.setattr(game.win, "capture", lambda h: None)
    assert runner._screenshot(1234) == (None, "game_window_not_in_front")
    monkeypatch.setattr(game.win, "capture", lambda h: b"DRAWN" if h == 7 else None)
    assert runner._screenshot(1234) == (b"DRAWN", "Warcraft III (captured behind other windows)")
    monkeypatch.setattr(game.win32gui, "GetForegroundWindow", lambda: 7)
    monkeypatch.setattr(game.win, "screenshot", lambda h: b"PNG" if h == 7 else b"wrong")
    assert runner._screenshot(1234) == (b"PNG", "Warcraft III")


def test_window_prefers_the_game_window(monkeypatch):
    runner = game.Game()
    monkeypatch.setattr(game.win, "processes", lambda name: [5])
    monkeypatch.setattr(game.win, "windows", lambda pid: {1: [10], 5: [11]}.get(pid, []))
    monkeypatch.setattr(game.win32gui, "GetWindowText", lambda h: "Warcraft III" if h == 11 else "Launcher")
    assert runner.window(1) == 11   # the process the launcher handed over to


@pytest.mark.game
def test_probe_reports_a_running_map(tmp_path):
    """game_test(probe=true) adds its own report trigger to a copy, so the map itself stays untouched."""
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops import probe

    jass = next(p for p in ladder_maps() if open_sample("ladder:" + p.name).read("war3map.wtg") is not None)
    target = tmp_path / "Probe Test.w3x"
    shutil.copyfile(jass, target)
    copy = probe.build(target, tmp_path / "probe" / target.name, Catalog(_storage(), balance="Custom_V1"), seconds=8)
    result = game.Game().test(copy, results=[probe.REPORT], timeout=240)
    assert result["missing"] == [], result
    report = probe.parse(result["results"][probe.REPORT])
    assert report["probe"] == "ok" and report["player0.units"] > 0 and target.read_bytes() == jass.read_bytes()


def test_capture_draws_a_window_behind_others():
    import win32gui
    from PIL import Image
    import io

    from wc3mcp.desktop import win

    shown = []
    win32gui.EnumWindows(lambda h, _: shown.append(h) if win32gui.IsWindowVisible(h) and not win32gui.IsIconic(h)
                         and win32gui.GetWindowText(h) else None, None)
    for h in shown:
        left, top, right, bottom = win32gui.GetWindowRect(h)
        if right - left > 100 and bottom - top > 100:
            png = win.capture(h)
            if png:
                assert Image.open(io.BytesIO(png)).size == (right - left, bottom - top)
                break
    else:
        pytest.skip("no capturable window on this desktop")
    assert win.capture(0) is None


def test_stock_unit_textures_are_benign_and_long_results_are_flagged():
    lines = [r"9/16 21:00:00.000  Solid texture substituted - Units\_skeletons\Gore_Diffuse.tif",
             "9/16 21:00:00.000  Solid texture substituted - Units/Creeps/TimberWolf/Wolf_Corpse_Diffuse.tif",
             r"9/16 21:00:00.000  Solid texture substituted - war3mapImported\Mine.tif"]
    keep, benign, _ = game.split_log(lines)
    assert benign == lines[:2] and keep == lines[2:]
    found = {"a.txt": ["short", "x" * 259], "b.txt": ["y" * 100]}
    assert game.truncated_lines(found) == {"a.txt": [1]}
