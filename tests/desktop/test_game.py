import shutil

import pytest

from corpus import _storage, ladder_maps, open_sample
from wc3mcp.desktop import game
from wc3mcp.errors import ToolError

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


def test_preload_strings_lose_the_games_escaping():
    text = r'call Preload( "icon=ReplaceableTextures\\CommandButtons\\BTNX.blp say \"hi\"" )'
    assert game.parse_preload(text) == [r'icon=ReplaceableTextures\CommandButtons\BTNX.blp say "hi"']


def _screen(kind, size=(1440, 774)):
    from PIL import Image, ImageDraw
    w, h = size
    image = Image.new("RGB", size, (60, 40, 25) if kind == "login" else (200, 170, 120))
    draw = ImageDraw.Draw(image)
    left, wide = w / 2 - h * 2 / 3, h * 4 / 3
    if kind == "login":
        draw.rectangle((left + 0.1 * wide, 0.12 * h, left + 0.9 * wide, 0.85 * h), fill=(0, 45, 110))
    elif kind in ("press_key", "loading"):
        end = 0.86 if kind == "press_key" else 0.5
        draw.rectangle((left + 0.14 * wide, 0.80 * h, left + end * wide, 0.86 * h), fill=(30, 120, 230))
        for x in range(10):   # the prompt's letters over the bar
            draw.rectangle((left + (0.3 + x * 0.04) * wide, 0.82 * h, left + (0.31 + x * 0.04) * wide, 0.84 * h),
                           fill=(250, 210, 40))
    return image


def test_screen_state_reads_login_and_waiting_loading_screens():
    assert game.screen_state(_screen("login")) == "login"
    assert game.screen_state(_screen("press_key")) == "press_key"
    assert game.screen_state(_screen("press_key", (1920, 1080))) == "press_key"
    assert game.screen_state(_screen("loading")) is None
    assert game.screen_state(_screen("game")) is None


def _fake_run(monkeypatch, tmp_path, states, write_result_after_key=False, runner=None, map_bytes=b"",
              launches=None, wait=True, login="stop", app=None, alerts=None, raised=None, **options):
    clock = {"now": 1000.0}
    fake_time = type("T", (), {"time": staticmethod(lambda: clock["now"]),
                               "sleep": staticmethod(lambda s: clock.__setitem__("now", clock["now"] + s))})
    process = type("P", (), {"pid": 42, "poll": lambda self: None})()
    exe = tmp_path / "Warcraft III.exe"
    exe.write_bytes(b"")
    (tmp_path / "map.w3x").write_bytes(map_bytes)
    monkeypatch.setenv("WC3MCP_DOCUMENTS", str(tmp_path / "docs"))
    monkeypatch.setattr(game, "time", fake_time)
    monkeypatch.setattr(game.subprocess, "Popen", lambda *a, **k: launches.append(a) or process
                        if launches is not None else process)
    monkeypatch.setattr(game.Game, "exe", staticmethod(lambda: exe))
    monkeypatch.setattr(game.Game, "window", lambda self, pid: 7)
    monkeypatch.setattr(game.win32gui, "GetForegroundWindow", lambda: 7)
    monkeypatch.setattr(game.win32gui, "IsWindow", lambda h: True)
    monkeypatch.setattr(game.win, "activate", lambda h: raised.append(h) if raised is not None else None)
    monkeypatch.setattr(game.win, "client_image", lambda h: None)
    closed, keys, shown = [], [], iter(states)
    monkeypatch.setattr(game.Game, "_close", lambda self, p: closed.append(p) or True)
    monkeypatch.setattr(game, "screen_state", lambda image: next(shown, None))
    monkeypatch.setattr(game.battlenet, "exe", lambda: tmp_path / "Battle.net.exe" if app else None)
    monkeypatch.setattr(game.battlenet, "forget_map", lambda: None)

    def launch_app(self, found, target):
        if callable(app):
            return app(self)
        if launches is not None:
            launches.append((str(target),))
        return (process, dict(app)) if app and app.get("ok") else (None, dict(app or {}))

    monkeypatch.setattr(game.Game, "_launch_app", launch_app)
    monkeypatch.setattr(game, "_alert", lambda window: alerts.append(window) if alerts is not None else None)

    def press(h, actions):
        keys.append(actions)
        if write_result_after_key:
            out = tmp_path / "docs" / "CustomMapData" / "t" / "r.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text('function PreloadFiles takes nothing returns nothing\n\tcall Preload( "ok" )\nendfunction\n')

    monkeypatch.setattr(game.win, "send_input", press)
    result = (runner or game.Game()).test(tmp_path / "map.w3x", timeout=300, results=[r"t\r.txt"], wait=wait,
                                          login=login, **options)
    return result, keys, closed


def test_a_waiting_loading_screen_gets_a_key(monkeypatch, tmp_path):
    result, keys, closed = _fake_run(monkeypatch, tmp_path, [None, "press_key"], write_result_after_key=True)
    assert keys == [[{"keys": "space"}]] and result["loading_screen_keys"] == 1
    assert result["results"] == {r"t\r.txt": ["ok"]} and closed and "login_required" not in result


def test_a_login_screen_ends_the_run_early_and_leaves_the_game_open(monkeypatch, tmp_path):
    result, keys, closed = _fake_run(monkeypatch, tmp_path, ["login"] * 100)
    assert result["login_required"] is True and "log in" in result["hint"]
    assert result["seconds"] < 60 and not closed and not keys
    result, _, _ = _fake_run(monkeypatch, tmp_path, ["login", "login", None] + [None] * 100)   # a remembered login
    assert "login_required" not in result


def test_the_same_test_after_a_login_continues_in_the_open_game(monkeypatch, tmp_path):
    runner, launches = game.Game(), []
    first, _, closed = _fake_run(monkeypatch, tmp_path, ["login"] * 20, runner=runner, launches=launches)
    assert first["login_required"] and "same arguments" in first["hint"] and not closed
    again, keys, closed = _fake_run(monkeypatch, tmp_path, ["press_key"], write_result_after_key=True, runner=runner,
                                    launches=launches)
    assert again["continued_game"] and again["results"] == {r"t\r.txt": ["ok"]} and len(launches) == 1
    _fake_run(monkeypatch, tmp_path, ["login"] * 20, runner=runner, launches=launches)
    other, _, closed = _fake_run(monkeypatch, tmp_path, ["press_key"], write_result_after_key=True, runner=runner,
                                 map_bytes=b"another map", launches=launches)
    assert "continued_game" not in other and len(launches) == 3 and len(closed) == 2   # the open game, then the run


def test_a_background_run_reports_its_result_through_the_status(monkeypatch, tmp_path):
    """wait=False returns at once and the run keeps going in a thread, so the working copy is free meanwhile."""
    runner = game.Game()
    started, _, _ = _fake_run(monkeypatch, tmp_path, [None, "press_key"], write_result_after_key=True, runner=runner,
                              wait=False)
    assert started["started"] and started["results"] == [r"t\r.txt"] and "game_status" in started["note"]
    runner.run["thread"].join(30)
    run = runner.status()["run"]
    assert run["state"] == "done" and run["background"] and run["written"] == [r"t\r.txt"]
    assert run["result"]["results"] == {r"t\r.txt": ["ok"]} and run["result"]["loading_screen_keys"] == 1


def test_a_second_run_while_one_is_going_is_refused(monkeypatch, tmp_path):
    from wc3mcp.errors import ToolError

    runner = game.Game()
    runner.run = {"map": str(tmp_path / "map.w3x"), "started": 1.0, "thread": type("T", (), {"is_alive": lambda s: True})(),
                  "timeout": 300, "results": [], "written": [], "result": None, "error": None, "meta": {}}
    with pytest.raises(ToolError) as e:
        _fake_run(monkeypatch, tmp_path, [None], runner=runner)
    assert e.value.code == "run_active" and "game_status" in e.value.hint
    assert runner.run_status()["state"] == "running" and "still going" in runner.run_status()["note"]


def test_screen_state_reads_the_main_menu():
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1440, 774), (30, 20, 15))
    draw = ImageDraw.Draw(image)
    w, h = image.size
    for k in range(4):   # the four teal buttons of the panel at the right edge
        y = (0.38 + k * 0.1) * h
        draw.rectangle((w - 0.49 * h, y, w - 0.20 * h, y + 0.05 * h), fill=(0, 45, 42))
    assert game.screen_state(image) == "menu"
    assert game.screen_state(_screen("login")) == "login" and game.screen_state(_screen("game")) is None


def test_auto_starts_the_game_through_the_battlenet_app_and_meets_no_login(monkeypatch, tmp_path):
    launches = []
    result, _, _ = _fake_run(monkeypatch, tmp_path, [None, "press_key"], write_result_after_key=True,
                             launches=launches, login="auto", app={"ok": True, "seconds": 12.0, "restarted": True})
    assert result["results"] == {r"t\r.txt": ["ok"]} and len(launches) == 1
    assert result["launched_by"] == "battlenet_app" and result["login"]["battlenet"]["restarted"]
    assert "login_required" not in result and result["login"]["screen_seen"] is False


def test_an_app_that_cannot_start_the_game_falls_back_to_a_direct_launch(monkeypatch, tmp_path):
    launches = []
    result, _, _ = _fake_run(monkeypatch, tmp_path, [None, "press_key"], write_result_after_key=True,
                             launches=launches, login="auto", app={"ok": False, "reason": "still updating"})
    assert result["launched_by"] == "directly" and len(launches) == 2   # the app's try, then the direct launch
    assert result["login"]["battlenet"]["reason"] == "still updating" and result["results"]


def test_a_login_screen_on_the_app_route_asks_the_user_to_log_in_to_the_app(monkeypatch, tmp_path):
    alerts = []
    result, _, closed = _fake_run(monkeypatch, tmp_path, ["login"] * 200, login="auto", alerts=alerts, login_wait=60,
                                  app={"ok": True})
    assert result["login_required"] and alerts == [7] and result["login"]["asked_user"] and not closed
    assert 60 <= result["seconds"] < 90 and "Battle.net app once" in result["hint"]
    alerts.clear()
    result, _, _ = _fake_run(monkeypatch, tmp_path, ["login"] * 5 + [None, "press_key"], write_result_after_key=True,
                             login="wait", alerts=alerts)
    assert result["results"] and alerts and "login_required" not in result and result["login"]["screen_seen"]


def test_login_battlenet_without_the_app_is_refused(monkeypatch, tmp_path):
    with pytest.raises(ToolError) as e:
        _fake_run(monkeypatch, tmp_path, [None] * 5, login="battlenet")
    assert e.value.code == "not_found" and "WC3MCP_BATTLENET" in e.value.hint


def test_a_game_stuck_at_the_main_menu_is_started_again(monkeypatch, tmp_path):
    launches = []
    result, _, _ = _fake_run(monkeypatch, tmp_path, ["menu"] * 6 + [None, "press_key"], write_result_after_key=True,
                             launches=launches)
    assert result["relaunched"] == ["stuck_at_main_menu"] and len(launches) == 2 and result["results"]
    result, _, _ = _fake_run(monkeypatch, tmp_path, ["menu"] * 100, launches=[])
    assert result["stuck_at"] == "main_menu" and len(result["relaunched"]) == game.MAX_RELAUNCHES


def test_the_screenshot_series_starts_when_the_map_runs(monkeypatch, tmp_path):
    marker = tmp_path / "docs" / "CustomMapData" / "wc3mcp" / "started.txt"

    def states():
        yield None
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("started")
        yield from [None] * 200

    monkeypatch.setattr(game.Game, "_screenshot", lambda self, pid: (b"png", "Warcraft III"))
    result, _, _ = _fake_run(monkeypatch, tmp_path, states(), started_file=r"wc3mcp\started.txt", shots=3,
                             shot_every=5)
    assert result["screenshots"] == [b"png"] * 3 and result["map_started_after"] > 0
    assert "from the moment the map ran" in result["screenshots_note"]
    monkeypatch.setattr(game.Game, "_screenshot", lambda self, pid: (None, "game_window_not_in_front"))
    result, _, _ = _fake_run(monkeypatch, tmp_path, [None] * 200, shots=2, shot_every=5)
    assert result["screenshots"] == [] and result["screenshots_failed"][0]["reason"] == "game_window_not_in_front"


def test_a_continued_game_is_left_to_the_user_and_a_timeout_on_the_login_keeps_it(monkeypatch, tmp_path):
    runner, launches = game.Game(), []
    first, _, closed = _fake_run(monkeypatch, tmp_path, ["login"] * 20, runner=runner, launches=launches)   # stop
    assert first["login_required"] and not closed
    again, _, closed = _fake_run(monkeypatch, tmp_path, ["login"] * 100, runner=runner, launches=launches,
                                 login="auto", app={"ok": True})
    assert again["continued_game"] and again["login_required"] and len(launches) == 1 and not closed
    timed, _, closed = _fake_run(monkeypatch, tmp_path, ["login"] * 400, login="wait", login_wait=1000)
    assert timed["login_required"] and not closed and timed["login_seconds"] > 0


def test_a_relaunch_brings_the_new_game_to_the_front_again(monkeypatch, tmp_path):
    raised = []
    result, _, _ = _fake_run(monkeypatch, tmp_path, [None] * 6 + ["menu"] * 6 + [None] * 40, launches=[],
                             raised=raised)
    assert result["relaunched"] == ["stuck_at_main_menu"] and len(raised) > 10   # no marker: it keeps raising


def test_game_close_stops_a_run_waiting_for_the_battlenet_app(monkeypatch, tmp_path):
    runner = game.Game()

    def waiting_app(self):
        self.close()   # the user gives up while the app is starting the game
        return None, {"ok": False, "reason": "cancelled"}

    result, _, _ = _fake_run(monkeypatch, tmp_path, ["login"] * 10, runner=runner, login="auto", app=waiting_app)
    assert result["cancelled"] and "relaunched" not in result and result["login"]["battlenet"]["ok"] is False


def test_every_run_gives_the_launcher_back_even_when_it_fails(monkeypatch, tmp_path):
    """A run that errors, times out or is killed must not leave the Battle.net app starting the test map."""
    g = game.Game()
    restored = []
    monkeypatch.setattr(game.battlenet, "restore", lambda: restored.append(1) or {"restored": True})

    def boom(*args, **kwargs):
        raise RuntimeError("the game crashed")

    monkeypatch.setattr(g, "_test", boom)
    job = {"result": None, "error": None}
    g._run(job, tmp_path / "Map.w3x", 10, [], True, False)
    assert restored == [1] and job["error"].code == "game_failed"

    monkeypatch.setattr(g, "_test", lambda *a, **k: {"missing": []})
    job = {"result": None, "error": None}
    g._run(job, tmp_path / "Map.w3x", 10, [], True, False)
    assert job["result"]["launcher"] == {"restored": True} and restored == [1, 1]
