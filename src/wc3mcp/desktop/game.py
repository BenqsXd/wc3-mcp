"""Game test runs: launch Warcraft III windowed on a map, collect Preload result files written by the map script
(PreloadGenEnd into Documents\\Warcraft III\\CustomMapData), keep the useful War3Log.txt lines, close the game.
Only processes started here are ever closed."""
import re
import subprocess
import time
from pathlib import Path, PureWindowsPath

import win32gui

from .. import config
from ..errors import ToolError
from . import win

EXE_NAME = "Warcraft III.exe"
PRELOAD = re.compile(r'call Preload\( "(.*)" \)')
NOISE = re.compile(r"^\S+ \S+\s+(?:Opening (?:map|mod) - |prism: Info)")
# lines the shipped Reforged data produces on every run: not defects of the map being tested
BENIGN = re.compile(r"model creation failed|Could not load file|Referencing unknown database field|"
                    r"Failed to load Environment Map|Unable to load MDX")
BENIGN_NOTE = "these come from the shipped game data and appear on any map"


def parse_preload(text: str) -> list[str]:
    return PRELOAD.findall(text)


def interesting(lines: list[str]) -> list[str]:
    return [line for line in lines if line.strip() and not NOISE.match(line)]


def split_log(lines: list[str]) -> tuple[list[str], list[str]]:
    """(lines worth reading, known-benign lines from the shipped game data)"""
    keep = interesting(lines)
    return [line for line in keep if not BENIGN.search(line)], [line for line in keep if BENIGN.search(line)]


def _result_path(name: str) -> Path:
    rel = PureWindowsPath(name)
    if rel.is_absolute() or rel.drive or ".." in rel.parts or not rel.parts:
        raise ToolError("bad_value", f"result {name!r} must be a path relative to CustomMapData",
                        hint='e.g. "mymap\\\\results.txt" for PreloadGenEnd("mymap\\\\results.txt")')
    return config.documents() / "CustomMapData" / Path(*rel.parts)


class Game:
    def __init__(self):
        self.launched: dict[int, subprocess.Popen] = {}

    @staticmethod
    def exe() -> Path:
        return config.install_root() / "_retail_" / "x86_64" / EXE_NAME

    @staticmethod
    def _log_lines(since: float | None = None) -> list[str]:
        path = config.documents() / "Logs" / "War3Log.txt"
        if not path.exists() or (since is not None and path.stat().st_mtime < since):
            return []
        return path.read_text("utf-8", "replace").splitlines()

    @staticmethod
    def _crash_folders() -> set[str]:
        folder = config.documents() / "Errors"
        return {p.name for p in folder.iterdir() if p.is_dir()} if folder.is_dir() else set()

    def windows(self, pid: int) -> list[int]:
        """Windows of the game: the process started here and any other Warcraft III process it handed over to."""
        pids = [pid] + [p for p in win.processes(EXE_NAME) if p != pid]
        return [h for p in pids for h in win.windows(p)]

    def window(self, pid: int) -> int | None:
        found = self.windows(pid)
        return next((h for h in found if "warcraft" in win32gui.GetWindowText(h).lower()), next(iter(found), None))

    def _screenshot(self, pid: int) -> tuple[bytes | None, str]:
        """(PNG of the game window, what was captured). Never grabs whatever else is on screen."""
        h = self.window(pid)
        if not h:
            return None, "no_game_window"
        win.activate(h)
        time.sleep(0.5)
        if win32gui.GetForegroundWindow() != h:
            return None, "game_window_not_in_front"
        return win.screenshot(h), win32gui.GetWindowText(h) or "the game window"

    def test(self, map_path, timeout: float = 240, results: list[str] | None = None, close: bool = True,
             screenshot: bool = False) -> dict:
        """Run the map. With `results`, returns as soon as every listed Preload file has been written; without
        them, runs for `timeout` seconds."""
        target = Path(map_path).resolve()
        if not target.exists():
            raise ToolError("not_found", f"no map at {target}")
        exe = self.exe()
        if not exe.is_file():
            raise ToolError("no_install", f"{exe} not found", hint="set WC3MCP_INSTALL")
        wanted = {name: _result_path(name) for name in results or []}
        for path in wanted.values():
            path.unlink(missing_ok=True)  # never read a stale result from an earlier run
        crashes = self._crash_folders()
        previous = win32gui.GetForegroundWindow()
        started = time.time()
        process = subprocess.Popen([str(exe), "-launch", "-loadfile", str(target), "-windowmode", "windowed",
                                    "-nowfpause"], cwd=exe.parent)
        self.launched[process.pid] = process
        found: dict[str, list[str]] = {}
        focused_at, running, raised = 0.0, False, 0
        while time.time() - started < timeout and process.poll() is None:
            # the game only loads the map while its window is in front: keep it there until the map runs
            running = running or any("Activating WebUI" in line for line in self._log_lines(started - 5))
            if not running and time.time() - focused_at > 5:
                window = self.window(process.pid)
                if window:
                    win.activate(window)
                    focused_at, raised = time.time(), raised + 1
            for name, path in wanted.items():
                if name not in found and path.exists():
                    text = path.read_text("utf-8", "replace")
                    if "endfunction" in text:  # PreloadGenEnd writes the whole file at once
                        found[name] = parse_preload(text)
            if wanted and len(found) == len(wanted):
                break
            time.sleep(1)
        log, benign = split_log(self._log_lines(started - 5))
        result = {"seconds": round(time.time() - started, 1), "pid": process.pid, "results": found,
                  "missing": [n for n in wanted if n not in found], "exited_early": process.poll() is not None,
                  "log": log[-200:], "benign_log": {"count": len(benign), "examples": benign[:3], "note": BENIGN_NOTE},
                  "crash": next(iter(sorted(self._crash_folders() - crashes)), None)}
        if result["missing"]:
            result["hint"] = ("no result file was written: a Battle.net login screen or a dialog stops the game before the "
                              "map loads (log in once with 'Keep me logged in'; screenshot=true shows the window), or the "
                              "map script failed (script_validate)")
        if screenshot:
            shot, of = self._screenshot(process.pid)
            result["screenshot"], result["screenshot_of"] = shot, of
        result["closed"] = self._close(process) if close else process.poll() is not None
        if focused_at and previous and win32gui.IsWindow(previous):
            win.activate(previous)
        result["focus"] = (f"the game window was brought to the front {raised} time(s) while loading" if raised
                           else "no game window appeared to bring to the front")
        return result

    def _close(self, process: subprocess.Popen) -> bool:
        if process.poll() is None:
            for h in win.windows(process.pid):
                win.close(h)
            try:
                process.wait(20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(10)
        self.launched.pop(process.pid, None)
        return True

    def status(self) -> dict:
        alive = {pid: p for pid, p in self.launched.items() if p.poll() is None}
        log, benign = split_log(self._log_lines())
        return {"running": bool(alive),
                "processes": [{"pid": pid, "launched_by_server": pid in alive} for pid in win.processes(EXE_NAME)],
                "windows": [win.info(h)["title"] for pid in alive for h in win.windows(pid)],
                "log": log[-50:], "benign_log": {"count": len(benign), "examples": benign[:3], "note": BENIGN_NOTE}}

    def close(self) -> dict:
        closed = [pid for pid, p in list(self.launched.items()) if self._close(p)]
        return {"closed": closed, "running": self.status()["running"]}


GAME = Game()
