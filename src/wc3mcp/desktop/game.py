"""Game test runs: launch Warcraft III windowed on a map, collect Preload result files written by the map script
(PreloadGenEnd into Documents\\Warcraft III\\CustomMapData), keep the useful War3Log.txt lines, close the game.
Only processes started here are ever closed."""
import hashlib
import re
import subprocess
import threading
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
BENIGN = re.compile(r"model creation failed|Referencing unknown database field|Failed to load Environment Map|"
                    r"Unable to load MDX|Solid texture substituted - Units[\\/]")
BENIGN_NOTE = "these come from the shipped game data and appear on any map"
MISSING = re.compile(r"Could not load file: (.+)$")
# the game keeps about 259 characters of one Preload string and silently drops the rest
PRELOAD_LIMIT = 255
# the login panel shows while a remembered login signs in (and an authenticator request waits); longer means the
# user has to log in
LOGIN_WAIT = 30
PAUSE_NOTE = ("an open dialog (DialogDisplay) pauses a single-player game until it is clicked, so timers and "
              "probe_seconds wait for it (screenshot=true shows it)")


def parse_preload(text: str) -> list[str]:
    """The Preload strings, without the escaping the game adds when it writes them (\\\\ and \\")."""
    return [re.sub(r'\\([\\"])', r"\1", s) for s in PRELOAD.findall(text)]


def _share(image, u0: float, v0: float, u1: float, v1: float, test) -> float:
    """Share of the pixels in a box passing `test`. v runs over the height; u over the centred 4:3 area the game lays
    out its menus and loading screen in."""
    w, h = image.size
    wide, x0 = h * 4 / 3, w / 2 - h * 2 / 3
    box = (max(0, int(x0 + u0 * wide)), int(v0 * h), min(w, int(x0 + u1 * wide)), int(v1 * h))
    if box[2] - box[0] < 2 or box[3] - box[1] < 2:
        return 0.0
    data = image.crop(box).convert("RGB").resize((48, 16)).tobytes()
    pixels = [data[i:i + 3] for i in range(0, len(data), 3)]
    return sum(map(test, pixels)) / len(pixels)


def _blue(p) -> bool:
    return p[2] > 60 and p[2] > p[0] + 40 and p[2] > p[1] + 15


def _bright_blue(p) -> bool:
    return p[2] > 150 and p[2] > p[0] + 60


def screen_state(image) -> str | None:
    """"login" when the game window shows the Battle.net login panel, "press_key" when a loading screen has finished
    and waits for a key (its bar is full and says PRESS ANY KEY TO CONTINUE), else None."""
    # ponytail: fixed boxes measured on a 1440x774 window; retune if other window sizes misread
    if _share(image, 0.15, 0.15, 0.85, 0.80, _blue) > 0.7 and _share(image, -0.05, 0.2, 0.05, 0.8, _blue) < 0.2:
        return "login"
    ends = (_share(image, 0.17, 0.815, 0.23, 0.84, _bright_blue), _share(image, 0.78, 0.815, 0.84, 0.84, _bright_blue))
    if min(ends) > 0.8 and _share(image, 0.45, 0.815, 0.55, 0.84, _bright_blue) > 0.25 \
            and _share(image, 0.15, 0.70, 0.85, 0.75, _bright_blue) < 0.1:
        return "press_key"
    return None


def truncated_lines(found: dict[str, list[str]]) -> dict[str, list[int]]:
    """Indexes of result lines long enough that the game has probably cut them off, per result file."""
    rows = {name: [i for i, line in enumerate(lines) if len(line) >= PRELOAD_LIMIT] for name, lines in found.items()}
    return {name: hits for name, hits in rows.items() if hits}


def interesting(lines: list[str]) -> list[str]:
    return [line for line in lines if line.strip() and not NOISE.match(line)]


def split_log(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """(lines worth reading, known-benign lines from the shipped game data, files the game could not load)"""
    keep = interesting(lines)
    missing = sorted({m.group(1).strip() for m in map(MISSING.search, keep) if m})
    keep = [line for line in keep if not MISSING.search(line)]
    return [line for line in keep if not BENIGN.search(line)], [line for line in keep if BENIGN.search(line)], missing


def _result_path(name: str) -> Path:
    rel = PureWindowsPath(name)
    if rel.is_absolute() or rel.drive or ".." in rel.parts or not rel.parts:
        raise ToolError("bad_value", f"result {name!r} must be a path relative to CustomMapData",
                        hint='e.g. "mymap\\\\results.txt" for PreloadGenEnd("mymap\\\\results.txt")')
    return config.documents() / "CustomMapData" / Path(*rel.parts)


class Game:
    def __init__(self):
        self.launched: dict[int, subprocess.Popen] = {}
        # the game a login_required run left open: (process, launch time, map digest, results)
        self.waiting: tuple[subprocess.Popen, float, str, list[str]] | None = None
        # a run started with wait=False: the thread running it, its progress and, once it ends, its result
        self.run: dict | None = None

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
        title = win32gui.GetWindowText(h) or "the game window"
        win.activate(h)
        time.sleep(0.5)
        if win32gui.GetForegroundWindow() != h:   # draw it from the window itself instead of grabbing the screen
            shot = win.capture(h)
            return (shot, f"{title} (captured behind other windows)") if shot else (None, "game_window_not_in_front")
        return win.screenshot(h), title

    def test(self, map_path, timeout: float = 240, results: list[str] | None = None, close: bool = True,
             screenshot: bool = False, wait: bool = True, meta: dict | None = None) -> dict:
        """Run the map, blocking until it ends. wait=False instead runs it in a background thread and returns at
        once; `status()` then reports the run and holds its result when it ends."""
        target = Path(map_path).resolve()
        if not target.exists():
            raise ToolError("not_found", f"no map at {target}")
        if not self.exe().is_file():
            raise ToolError("no_install", f"{self.exe()} not found", hint="set WC3MCP_INSTALL")
        if self.run is not None and self.run["thread"] is not None and self.run["thread"].is_alive():
            raise ToolError("run_active", f"the game_test run of {Path(self.run['map']).name} started "
                            f"{round(time.time() - self.run['started'])} s ago is still running",
                            hint="game_status reports it (and its result once it ends); game_close ends it")
        job = {"map": str(target), "started": time.time(), "timeout": timeout, "results": sorted(results or []),
               "written": [], "result": None, "error": None, "thread": None, "meta": meta or {}}
        self.run = job
        if wait:
            self._run(job, target, timeout, results, close, screenshot)
            if job["error"] is not None:
                raise job["error"]
            return job["result"]
        job["thread"] = threading.Thread(target=self._run, daemon=True,
                                         args=(job, target, timeout, results, close, screenshot))
        job["thread"].start()
        return {"started": True, "map": str(target), "timeout": timeout, "results": job["results"],
                "note": "the run continues in the background: game_status reports its progress and, once it ends, its "
                        "whole result under run.result (the working copy is free meanwhile; a probe runs on a copy)"}

    def _run(self, job: dict, target: Path, timeout: float, results, close: bool, screenshot: bool) -> None:
        try:
            job["result"] = self._test(job, target, timeout, results, close, screenshot)
        except ToolError as e:
            job["error"] = e
        except Exception as e:   # a background run must not take the server down
            job["error"] = ToolError("game_failed", f"the run failed: {e}")

    def _test(self, job: dict, target: Path, timeout: float, results: list[str] | None, close: bool,
              screenshot: bool) -> dict:
        exe = self.exe()
        wanted = {name: _result_path(name) for name in results or []}
        digest = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else str(target)
        waiting, self.waiting = self.waiting, None
        attached = bool(waiting and waiting[0].poll() is None and waiting[2:] == (digest, sorted(wanted)))
        if waiting and not attached:
            self._close(waiting[0])   # a different test: the game left open for a login holds its own map
        crashes = self._crash_folders()
        previous = win32gui.GetForegroundWindow()
        started = time.time()
        if attached:   # the same test again after the user logged in: continue in that game, no new launch
            process, launched_at = waiting[0], waiting[1]
        else:
            for path in wanted.values():
                path.unlink(missing_ok=True)  # never read a stale result from an earlier run
            process, launched_at = subprocess.Popen([str(exe), "-launch", "-loadfile", str(target), "-windowmode",
                                                     "windowed", "-nowfpause"], cwd=exe.parent), started
            self.launched[process.pid] = process
        found: dict[str, list[str]] = {}
        focused_at, running, raised = 0.0, False, 0
        checked_at, login_since, keys = 0.0, None, 0
        while time.time() - started < timeout and process.poll() is None:
            # the game only loads the map while its window is in front: keep it there until the map runs
            running = running or any("Activating WebUI" in line for line in self._log_lines(launched_at - 5))
            if not running and time.time() - focused_at > 5:
                window = self.window(process.pid)
                if window:
                    win.activate(window)
                    focused_at, raised = time.time(), raised + 1
            # what the window shows: a login panel ends the run early, a finished loading screen gets its key
            window = self.window(process.pid) if time.time() - checked_at > 5 else None
            if window and win32gui.GetForegroundWindow() == window:
                checked_at = time.time()
                try:
                    state = screen_state(win.client_image(window))
                except (win32gui.error, OSError):
                    state = None
                if state == "press_key":
                    win.send_input(window, [{"keys": "space"}])
                    keys += 1
                login_since = (login_since or checked_at) if state == "login" else None
                if login_since and checked_at - login_since >= LOGIN_WAIT:
                    break
            for name, path in wanted.items():
                if name not in found and path.exists():
                    text = path.read_text("utf-8", "replace")
                    if "endfunction" in text:  # PreloadGenEnd writes the whole file at once
                        found[name] = parse_preload(text)
                        job["written"] = sorted(found)
            if wanted and len(found) == len(wanted):
                break
            time.sleep(1)
        log, benign, missing_files = split_log(self._log_lines(launched_at - 5))
        result = {"seconds": round(time.time() - started, 1), "pid": process.pid, "results": found,
                  "missing": [n for n in wanted if n not in found], "exited_early": process.poll() is not None,
                  "log": log[-200:], "benign_log": {"count": len(benign), "examples": benign[:3], "note": BENIGN_NOTE},
                  "missing_files": missing_files[:50],
                  "crash": next(iter(sorted(self._crash_folders() - crashes)), None)}
        login = bool(login_since and checked_at - login_since >= LOGIN_WAIT)
        if keys:
            result["loading_screen_keys"] = keys
            result["loading_screen_note"] = ("the loading screen waited for a key (the map sets loading_screen title, "
                                             "subtitle or text), so the run pressed space to continue")
        truncated = truncated_lines(found)
        if truncated:
            result["truncated"] = truncated
            result["truncated_note"] = ("these result lines (indexes per file) reach the Preload limit of about 259 "
                                        "characters, so the game probably cut them off: split long reports into "
                                        "several Preload calls")
        if attached:
            result["continued_game"] = True
        if login:
            self.waiting = (process, launched_at, digest, sorted(wanted))
            result["login_required"] = True
            result["hint"] = ("the game shows the Battle.net login screen: ask the user to log in there (with 'Keep me "
                              "logged in'), then call game_test again with the same arguments: it continues in that "
                              "game instead of launching a new one, which could ask for a login again")
        elif result["missing"]:
            result["hint"] = ("no result file was written: the map script failed (script_validate), the game stayed on "
                              f"a login screen, the map did not get that far before timeout, or {PAUSE_NOTE}")
        if screenshot:
            shot, of = self._screenshot(process.pid)
            result["screenshot"], result["screenshot_of"] = shot, of
        result["closed"] = self._close(process) if close and not login else process.poll() is not None
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

    def run_status(self) -> dict | None:
        """The last game_test run: how far a background run is, or the result it ended with."""
        job = self.run
        if job is None:
            return None
        alive = job["thread"] is not None and job["thread"].is_alive()
        out = {"state": "running" if alive else "failed" if job["error"] is not None else "done",
               "map": job["map"], "seconds": round(time.time() - job["started"], 1), "timeout": job["timeout"],
               "results": job["results"], "written": job["written"], "background": job["thread"] is not None}
        if alive:
            out["note"] = ("the run is still going: call game_status again for its result (the map's own working copy "
                           "is free while it runs)")
        elif job["error"] is not None:
            out["error"] = job["error"].to_dict()
        elif job["result"] is not None:
            out["result"] = job["result"]
        return out

    def status(self) -> dict:
        alive = {pid: p for pid, p in self.launched.items() if p.poll() is None}
        log, benign, missing_files = split_log(self._log_lines())
        run = self.run_status()
        return {"running": bool(alive),
                "processes": [{"pid": pid, "launched_by_server": pid in alive} for pid in win.processes(EXE_NAME)],
                "windows": [win.info(h)["title"] for pid in alive for h in win.windows(pid)],
                **({"run": run} if run else {}),
                "log": log[-50:], "benign_log": {"count": len(benign), "examples": benign[:3], "note": BENIGN_NOTE},
                "missing_files": missing_files[:50]}

    def close(self) -> dict:
        closed = [pid for pid, p in list(self.launched.items()) if self._close(p)]
        job = self.run
        if job is not None and job["thread"] is not None and job["thread"].is_alive():
            job["thread"].join(30)   # closing the game ends its loop; then the run can report what it collected
        return {"closed": closed, "running": self.status()["running"],
                **({"run": self.run_status()} if self.run else {})}


GAME = Game()
