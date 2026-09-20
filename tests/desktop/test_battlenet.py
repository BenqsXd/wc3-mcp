"""Starting the game through the Battle.net desktop app: the launch options it reads, and the launch itself."""
import json

from wc3mcp.desktop import battlenet


def _config(tmp_path, monkeypatch, data=None):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("WC3MCP_HOME", str(tmp_path / "home"))
    path = tmp_path / "Battle.net" / "Battle.net.config"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data if data is not None else {"Games": {"w3": {"ServerUid": "w3"}}}), "utf-8")
    return path


def test_the_map_is_quoted_so_a_path_with_spaces_survives(tmp_path):
    args = battlenet.game_args(tmp_path / "My Maps" / "map.w3x")
    assert args.startswith('-loadfile "') and str(tmp_path / "My Maps" / "map.w3x") in args
    assert "-windowmode windowed" in args and "-nowfpause" in args


def test_configure_writes_the_launch_options_and_restarts_the_app_once(tmp_path, monkeypatch):
    path = _config(tmp_path, monkeypatch, {"Games": {"w3": {"AdditionalLaunchArguments": "-opengl"}}})
    stops, starts = [], []
    monkeypatch.setattr(battlenet, "_stop", lambda: stops.append(1))
    monkeypatch.setattr(battlenet, "_start", lambda app: starts.append(app))
    target = tmp_path / "launch" / "map.w3x"

    first = battlenet.configure(tmp_path / "Battle.net.exe", target)
    assert first["restarted"] and first["replaced"] == "-opengl" and len(stops) == len(starts) == 1
    stored = json.loads(path.read_text("utf-8"))["Games"]["w3"]
    assert stored["AdditionalLaunchArguments"] == battlenet.game_args(target) and stored.get("ServerUid") is None
    assert battlenet.stored_args() == battlenet.game_args(target)
    # the app keeps only the keys it knows, so what it replaced is kept where the server can find it again
    assert (tmp_path / "home" / "battlenet-previous-launch-arguments.txt").read_text("utf-8") == "-opengl"

    again = battlenet.configure(tmp_path / "Battle.net.exe", target)
    assert again == {"restarted": False, "args": battlenet.game_args(target)} and len(stops) == 1


def test_stored_args_of_a_machine_without_the_app(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "nothing"))
    assert battlenet.stored_args() == ""


def test_the_launch_copy_is_one_path_and_goes_away_after_a_run(tmp_path, monkeypatch):
    monkeypatch.setenv("WC3MCP_HOME", str(tmp_path / "home"))
    source = tmp_path / "probe" / "run" / "Map.w3x"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"MAP")
    copy = battlenet.copy_map(source)
    assert copy == battlenet.launch_copy() and copy.read_bytes() == b"MAP"
    assert battlenet.copy_map(tmp_path / "probe" / "run" / "Map.w3x") == copy   # a second run, the same path
    battlenet.forget_map()
    assert not copy.exists()
    battlenet.forget_map()   # nothing there: still fine


def test_launch_asks_the_app_again_while_it_is_still_starting(tmp_path, monkeypatch):
    clock = {"now": 0.0}
    monkeypatch.setattr(battlenet.time, "time", lambda: clock["now"])
    monkeypatch.setattr(battlenet.time, "sleep", lambda s: clock.__setitem__("now", clock["now"] + s))
    asked = []
    monkeypatch.setattr(battlenet.subprocess, "Popen", lambda args: asked.append(clock["now"]))
    seen = {"pids": [4]}
    monkeypatch.setattr(battlenet.win, "processes", lambda name: seen["pids"] if clock["now"] < 40 else [4, 99])

    pid, info = battlenet.launch(tmp_path / "Battle.net.exe", "Warcraft III.exe")
    assert pid == 99 and info["ok"] and info["seconds"] >= 40
    assert len(asked) > 1 and asked[1] - asked[0] >= battlenet.ASK_AGAIN

    clock["now"] = 0.0
    monkeypatch.setattr(battlenet.win, "processes", lambda name: [4])
    pid, info = battlenet.launch(tmp_path / "Battle.net.exe", "Warcraft III.exe")
    assert pid is None and not info["ok"] and "Keep me logged in" in info["reason"]


def test_processes_reads_the_task_list(monkeypatch):
    rows = '"Battle.net.exe","20704","Console","1","250,000 K"\n"Battle.net.exe","10004","Console","1","90,000 K"\n'
    monkeypatch.setattr(battlenet.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": rows, "returncode": 0})())
    assert battlenet.processes() == [20704, 10004]
