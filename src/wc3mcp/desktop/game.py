"""Game test runs: launch Warcraft III windowed on a map, collect Preload result files written by the map script
(PreloadGenEnd into Documents\\Warcraft III\\CustomMapData), keep the useful War3Log.txt lines, close the game.
Only processes started here are ever closed."""
import hashlib
import re
import subprocess
import threading
import time
from collections import Counter
from pathlib import Path, PureWindowsPath

import win32gui

from .. import config
from ..errors import ToolError
from . import battlenet, win

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
LOGIN_SETTLE = 10        # seconds of login panel before anything is done about it: a remembered login signs in first
USER_LOGIN_WAIT = 120    # how long a run waits for the user to log in by hand (login="wait", or auto after Battle.net)
# how the game is started, which decides whether it meets the Battle.net login panel at all: "auto" (default) and
# "battlenet" start it through the Battle.net desktop app, which hands it the app's own session (see battlenet.py);
# "wait" and "stop" start it directly, which means a login panel unless the game still has a session of its own -
# "wait" then asks the user and waits, "stop" ends the run with login_required (the game stays open for the same
# call to continue in). "auto" falls back to the "wait" behaviour when the app is not installed or cannot start it.
LOGIN_MODES = ("auto", "battlenet", "wait", "stop")
MENU_WAIT = 20           # seconds at the main menu after a -loadfile launch before the run starts the game again
MAX_RELAUNCHES = 2
PAUSE_NOTE = ("an open dialog (DialogDisplay) pauses a single-player game until it is clicked, so timers and "
              "probe_seconds wait for it (screenshot=true shows it; probe_init runs before any dialog opens)")
LEFT_OPEN_NOTE = ("the game is still open on the test map, so the Battle.net app still starts Warcraft III on it: "
                  "game_close ends the game and puts the app's launch options back")


def _alert(window: int) -> None:
    """Get the user's attention to the game window: it flashes in the taskbar and Windows plays its warning sound."""
    import winsound

    import win32con

    try:
        win.activate(window)
        win32gui.FlashWindowEx(window, win32con.FLASHW_ALL | win32con.FLASHW_TIMERNOFG, 20, 0)
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except (win32gui.error, RuntimeError, OSError):
        pass


class _AppGame:
    """A game the Battle.net app started for a run: the part of subprocess.Popen the run loop and _close() use, so
    a game started through the app is handled like one this server started itself."""

    def __init__(self, pid: int):
        self.pid = pid

    def poll(self) -> int | None:
        return None if win.running(self.pid) else 0

    def wait(self, timeout: float | None = None) -> int:
        deadline = time.time() + (timeout if timeout is not None else 3600)
        while time.time() < deadline:
            if not win.running(self.pid):
                return 0
            time.sleep(0.5)
        raise subprocess.TimeoutExpired(EXE_NAME, timeout or 0)

    def kill(self) -> None:
        subprocess.run(["taskkill", "/PID", str(self.pid), "/F"], capture_output=True, check=False)


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


def _teal(p) -> bool:
    return p[0] < 14 and 24 < p[1] < 75 and 18 < p[2] < 75


def _menu_buttons(image) -> float:
    """Share of dark teal in the column where the main menu stacks its buttons (the panel hangs at the right edge,
    sized by the window height)."""
    w, h = image.size
    box = (int(w - 0.50 * h), int(0.37 * h), int(w - 0.19 * h), int(0.75 * h))
    if box[0] < 0 or box[2] - box[0] < 2:
        return 0.0
    data = image.crop(box).convert("RGB").resize((24, 48)).tobytes()
    pixels = [data[i:i + 3] for i in range(0, len(data), 3)]
    return sum(map(_teal, pixels)) / len(pixels)


def screen_state(image) -> str | None:
    """"login" when the game window shows the Battle.net login panel, "press_key" when a loading screen has finished
    and waits for a key (its bar is full and says PRESS ANY KEY TO CONTINUE), "menu" at the main menu, else None."""
    # ponytail: fixed boxes measured on a 1440x774 window; retune if other window sizes misread
    if _share(image, 0.15, 0.15, 0.85, 0.80, _blue) > 0.7 and _share(image, -0.05, 0.2, 0.05, 0.8, _blue) < 0.2:
        return "login"
    ends = (_share(image, 0.17, 0.815, 0.23, 0.84, _bright_blue), _share(image, 0.78, 0.815, 0.84, 0.84, _bright_blue))
    if min(ends) > 0.8 and _share(image, 0.45, 0.815, 0.55, 0.84, _bright_blue) > 0.25 \
            and _share(image, 0.15, 0.70, 0.85, 0.75, _bright_blue) < 0.1:
        return "press_key"
    if _menu_buttons(image) > 0.2:   # 0.32 at the main menu, at most 0.05 on every other saved frame
        return "menu"
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
        self.cancelled = False           # game_close asked the running test to stop

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
             screenshot: bool = False, wait: bool = True, meta: dict | None = None, shots: int = 0,
             shot_every: float = 3.0, login: str = "auto", login_wait: float = USER_LOGIN_WAIT,
             started_file: str | None = None) -> dict:
        """Run the map, blocking until it ends. wait=False instead runs it in a background thread and returns at
        once; `status()` then reports the run and holds its result when it ends. login says what a Battle.net login
        screen gets (LOGIN_MODES); started_file is a result file the map writes the moment it runs (the probe's)."""
        target = Path(map_path).resolve()
        if not target.exists():
            raise ToolError("not_found", f"no map at {target}")
        if not self.exe().is_file():
            raise ToolError("no_install", f"{self.exe()} not found", hint="set WC3MCP_INSTALL")
        if login not in LOGIN_MODES:
            raise ToolError("bad_value", f"login: expected one of {', '.join(LOGIN_MODES)}", path="login")
        if self.run is not None and self.run["thread"] is not None and self.run["thread"].is_alive():
            raise ToolError("run_active", f"the game_test run of {Path(self.run['map']).name} started "
                            f"{round(time.time() - self.run['started'])} s ago is still running",
                            hint="game_status reports it (and its result once it ends); game_close ends it")
        job = {"map": str(target), "started": time.time(), "timeout": timeout, "results": sorted(results or []),
               "written": [], "result": None, "error": None, "thread": None, "meta": meta or {}}
        self.run = job
        options = {"shots": shots, "shot_every": shot_every, "login": login, "login_wait": login_wait,
                   "started_file": started_file}
        if wait:
            self._run(job, target, timeout, results, close, screenshot, options)
            if job["error"] is not None:
                raise job["error"]
            return job["result"]
        job["thread"] = threading.Thread(target=self._run, daemon=True,
                                         args=(job, target, timeout, results, close, screenshot, options))
        job["thread"].start()
        return {"started": True, "map": str(target), "timeout": timeout, "results": job["results"],
                "note": "the run continues in the background: game_status reports its progress and, once it ends, its "
                        "whole result under run.result (the working copy is free meanwhile; a probe runs on a copy)"}

    def _run(self, job: dict, target: Path, timeout: float, results, close: bool, screenshot: bool,
             options: dict | None = None) -> None:
        try:
            job["result"] = self._test(job, target, timeout, results, close, screenshot, **(options or {}))
        except ToolError as e:
            job["error"] = e
        except Exception as e:   # a background run must not take the server down
            job["error"] = ToolError("game_failed", f"the run failed: {e}")
        finally:
            # every exit path - result files, timeout, kill, error - gives the user their launcher back, unless the
            # game was left open on purpose (close=false, or waiting for a login)
            if any(p.poll() is None for p in self.launched.values()):
                launcher = {"restored": False, "note": LEFT_OPEN_NOTE} if battlenet.ours() else None
            else:
                try:
                    launcher = battlenet.restore()
                except Exception as e:   # noqa: BLE001 - never lose the run's result over the launcher
                    launcher = {"restored": False, "error": str(e),
                                "note": "game_close tries again; game_status shows what the app would start"}
            if launcher is not None and job["result"] is not None:
                job["result"]["launcher"] = launcher

    def _launch(self, target: Path) -> subprocess.Popen:
        exe = self.exe()
        process = subprocess.Popen([str(exe), "-launch", "-loadfile", str(target), "-windowmode", "windowed",
                                    "-nowfpause"], cwd=exe.parent)
        self.launched[process.pid] = process
        return process

    def _launch_app(self, app: Path, target: Path):
        """Start the map through the Battle.net app, which hands the game the app's own session, so the run never
        meets the login panel. Returns (the game, what the app did); the game is None when none started."""
        try:
            copy = battlenet.copy_map(target)
        except OSError as e:
            raise ToolError("file_in_use", f"the map the Battle.net app launches could not be written: {e}",
                            hint="a game from an earlier run still holds it: game_close, then this call again")
        info = battlenet.configure(app, copy)
        pid, started = battlenet.launch(app, EXE_NAME)
        info.update(started)
        if pid is None:
            return None, info
        process = _AppGame(pid)
        self.launched[pid] = process
        return process, info

    def _test(self, job: dict, target: Path, timeout: float, results: list[str] | None, close: bool,
              screenshot: bool, shots: int = 0, shot_every: float = 3.0, login: str = "auto",
              login_wait: float = USER_LOGIN_WAIT, started_file: str | None = None) -> dict:
        wanted = {name: _result_path(name) for name in results or []}
        marker = _result_path(started_file) if started_file else None
        digest = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else str(target)
        waiting, self.waiting = self.waiting, None
        attached = bool(waiting and waiting[0].poll() is None and waiting[2:] == (digest, sorted(wanted)))
        if waiting and not attached:
            self._close(waiting[0])   # a different test: the game left open for a login holds its own map
        self.cancelled = False
        crashes = self._crash_folders()
        previous = win32gui.GetForegroundWindow()
        started = time.time()
        app = battlenet.exe() if login in ("auto", "battlenet") and not attached else None
        if login == "battlenet" and app is None and not attached:
            raise ToolError("not_found", "no Battle.net app found, so the game cannot be started through it",
                            hint="install it, or set WC3MCP_BATTLENET to its Battle.net.exe, or use login='wait' "
                                 "(the game then asks the user to log in)")
        through_app, launch_info = False, None
        if attached:   # the same test again after the user logged in: continue in that game, no new launch
            process, launched_at = waiting[0], waiting[1]
        else:
            for path in [*wanted.values(), *([marker] if marker else [])]:
                path.unlink(missing_ok=True)  # never read a stale result from an earlier run
            process, launched_at = None, started
            if app is not None:   # the app hands the game its session: no login panel (battlenet.py)
                process, launch_info = self._launch_app(app, target)
                through_app = process is not None
            if process is None:
                process = self._launch(target)
        found: dict[str, list[str]] = {}
        focused_at, raised, keys = 0.0, 0, 0
        holders: Counter = Counter()   # (exe, title) of whatever held the foreground when the game was raised
        holder_pids: dict[tuple, int] = {}
        launcher, minimized = None, 0   # the Battle.net app's pids; its windows get minimised once the game shows
        checked_at, state = 0.0, None
        login_since, menu_since, map_since = None, None, None
        outcome, relaunches, asked_user, login_seen = None, [], False, False
        shot_at, series, missed = 0.0, [], []
        grace = 0.0   # time spent on login screens: it does not count against the timeout
        while process.poll() is None and not self.cancelled:
            now = time.time()
            if now - started >= timeout + grace + (now - login_since if login_since else 0):
                break   # time at a login screen never counts against the timeout: login_wait bounds that
            # the map runs: the probe's start marker is there, or (no marker) the screen has shown neither the login,
            # the main menu nor a finished loading screen for a while - good enough to start the screenshots
            if map_since is None and ((marker is not None and marker.exists()) or (
                    marker is None and state is None and checked_at and now - launched_at >= 20)):
                map_since = now
            # the game only loads the map while its window is in front: keep it there until the map surely runs
            if (map_since is None or marker is None) and now - focused_at > 5:
                window = self.window(process.pid)
                if window:
                    fg = win32gui.GetForegroundWindow()
                    holder = None
                    if fg and fg != window:
                        try:
                            who = win.owner(fg)
                        except win32gui.error:
                            who = None
                        if who:
                            holder = (who["exe"], who["title"])
                            holders[holder] += 1
                            holder_pids[holder] = who["pid"]
                    # the restarted Battle.net app takes the foreground from the loading game: minimise it
                    if launcher is None or (holder and holder_pids[holder] in launcher):
                        first = launcher is None
                        launcher = battlenet.processes()
                        if first or (holder and holder_pids[holder] in launcher):
                            for pid in launcher:
                                for h in win.windows(pid):
                                    win.minimize(h)
                                    minimized += 1
                    win.activate(window)
                    focused_at, raised = now, raised + 1
            window = self.window(process.pid) if now - checked_at > 3 else None
            restart = None
            if window and win32gui.GetForegroundWindow() == window:
                checked_at = now
                try:
                    state = screen_state(win.client_image(window))
                except (win32gui.error, OSError):
                    state = None
                if state == "press_key":
                    win.send_input(window, [{"keys": "space"}])
                    keys += 1
                if login_since and state != "login":
                    grace += now - login_since   # the user (or a remembered login) signed in meanwhile
                login_since = (login_since or now) if state == "login" else None
                menu_since = (menu_since or now) if state == "menu" else None
                login_seen = login_seen or state == "login"
                if login_since:
                    # through the app this means the app itself is logged out, directly it means the game has no
                    # session of its own: either way only the user can sign in here, and no password is ever typed
                    waited = now - login_since
                    if login == "stop":
                        if waited >= LOGIN_WAIT:
                            outcome = "login_required"
                            break
                    elif waited >= LOGIN_SETTLE:
                        if not asked_user:
                            _alert(window)
                            asked_user = True
                        if waited >= login_wait:
                            outcome = "login_required"
                            break
                # at the main menu instead of the map (the game can drop -loadfile after a login): start again - but
                # not once the probe's marker shows the map ran (the map itself may have ended the game)
                if menu_since and now - menu_since >= MENU_WAIT and not (marker is not None and map_since):
                    if len(relaunches) >= MAX_RELAUNCHES:
                        outcome = "stuck_at_menu"
                        break
                    restart = "stuck_at_main_menu"
            if restart:
                if process.poll() is None:
                    self._close(process)
                if marker is not None:
                    marker.unlink(missing_ok=True)
                again = self._launch_app(app, target)[0] if through_app and app is not None else None
                process, launched_at = again or self._launch(target), time.time()
                login_since = menu_since = map_since = None
                state, checked_at, focused_at = None, 0.0, 0.0
                relaunches.append(restart)
                continue
            if map_since is not None and len(series) + len(missed) < shots and now - shot_at >= shot_every:
                shot_at = now
                image, of = self._screenshot(process.pid)
                if image:
                    series.append(image)
                else:
                    missed.append({"t": round(now - map_since, 1), "reason": of})
            for name, path in wanted.items():
                if name not in found and path.exists():
                    text = path.read_text("utf-8", "replace")
                    if "endfunction" in text:  # PreloadGenEnd writes the whole file at once
                        found[name] = parse_preload(text)
                        job["written"] = sorted(found)
            if wanted and len(found) == len(wanted):
                break
            time.sleep(1)
        if login_since:
            grace += time.time() - login_since
            if outcome is None and process.poll() is None and not self.cancelled:
                outcome = "login_required"   # the run ended on the login screen: keep the game for the user
        raw_log = self._log_lines(launched_at - 5)
        log, benign, missing_files = split_log(raw_log)
        result = {"seconds": round(time.time() - started, 1), "pid": process.pid, "results": found,
                  "missing": [n for n in wanted if n not in found], "exited_early": process.poll() is not None,
                  "log": log[-200:], "benign_log": {"count": len(benign), "examples": benign[:3], "note": BENIGN_NOTE},
                  "missing_files": missing_files[:50],
                  "crash": next(iter(sorted(self._crash_folders() - crashes)), None)}
        if self.cancelled:
            result["cancelled"] = True
        if grace:
            result["login_seconds"] = round(grace, 1)
        if map_since is not None:
            result["map_started_after"] = round(map_since - started, 1)
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
        if shots:
            result["screenshots"] = series
            if missed:
                result["screenshots_failed"] = missed
            result["screenshots_note"] = (
                f"{len(series)} of {shots} screenshot(s), one every {shot_every:g} s from the moment the map ran "
                + ("(the probe's start marker)" if marker else "(the screen left the menus and the loading screen)")
                + "; the run ends when its results are written, so a series longer than the test is cut short. "
                  "Move the camera from the map's test code (ProbeCamera) to look at a place"
                + ("" if map_since is not None else ". The map never started, so there are none"))
        if attached:
            result["continued_game"] = True
        if not attached:
            result["launched_by"] = "battlenet_app" if through_app else "directly"
        if launch_info is not None or asked_user or login_seen:
            result["login"] = {"mode": login, "screen_seen": login_seen,
                               **({"battlenet": launch_info} if launch_info is not None else {}),
                               **({"asked_user": True} if asked_user else {})}
        if relaunches:
            result["relaunched"] = relaunches
        if outcome == "login_required":
            self.waiting = (process, launched_at, digest, sorted(wanted))
            result["login_required"] = True
            result["hint"] = (("the game started through the Battle.net app still shows its login screen, so the app "
                               "itself is logged out: ask the user to log in to the Battle.net app once (with 'Keep "
                               "me logged in'); runs after that need no login at all"
                               if through_app else
                               "the Battle.net app could not start the game (login.battlenet says why), so it was "
                               "started directly and asks for a login: ask the user to log in to the app and to let "
                               "it finish any update"
                               if launch_info is not None else
                               "the game was started directly, which asks for a login unless it still has a session: "
                               "ask the user to log in there, or use login='auto' so the Battle.net app starts the "
                               "game and hands it its own session")
                              + ". Then call game_test again with the same arguments: it continues in the game left "
                                "open instead of launching a new one")
        elif outcome == "stuck_at_menu":
            result["stuck_at"] = "main_menu"
            result["hint"] = ("the game stayed at its main menu instead of loading the map, also after starting it "
                              "again: take a screenshot (screenshot=true) and tell the user")
        elif map_since is None and not self.cancelled and any(
                "Opening map - " in line or "already encountered" in line for line in raw_log):
            # every map writes "Opening map - <path>" when it loads (checked in War3Log.txt)
            top = holders.most_common(1)
            result["stuck_at"] = "loading_screen"
            result["hint"] = ("the map loaded but the key press that leaves the loading screen never reached the "
                              "game; the foreground belonged to "
                              + (f"{top[0][0][0]} ({top[0][0][1]!r})" if top else "another window")
                              + ". Leave the game window in front")
        elif result["missing"]:
            result["hint"] = ("no result file was written: the map script failed (script_validate), the game stayed on "
                              f"a login screen, the map did not get that far before timeout, or {PAUSE_NOTE}")
        if screenshot:
            shot, of = self._screenshot(process.pid)
            result["screenshot"], result["screenshot_of"] = shot, of
        if close and outcome != "login_required":
            result["closed_by"] = self._close(process)
            result["closed"] = True
        else:
            result["closed"] = process.poll() is not None
        if focused_at and previous and win32gui.IsWindow(previous):
            win.activate(previous)
        result["focus"] = {
            "raised": raised,
            "lost_to": [{"exe": exe, "title": title, "count": n} for (exe, title), n in holders.most_common(3)],
            "note": (f"the game window was brought to the front {raised} time(s) while loading" if raised
                     else "no game window appeared to bring to the front")}
        if minimized:
            result["launcher_minimized"] = minimized
        return result

    def _close(self, process: subprocess.Popen) -> str:
        """End a game this server launched: "exited" (it had), "closed" (it quit when its window was closed) or
        "killed" (it did not within 20 s)."""
        how = "exited"
        if process.poll() is None:
            for h in win.windows(process.pid):
                win.close(h)
            try:
                process.wait(20)
                how = "closed"
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(10)
                how = "killed"
        self.launched.pop(process.pid, None)
        return how

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
                "missing_files": missing_files[:50], "launcher": self._launcher()}

    @staticmethod
    def _launcher() -> dict:
        """What a Play in the Battle.net app starts today; a run leaves it pointing at a test map only while the game
        is open, and game_close puts it back."""
        out = battlenet.state()
        if out["points_at_test_map"] or out["launch_copy"]:
            out["note"] = ("the Battle.net app would start Warcraft III on a test map: game_close puts the user's own "
                           "launch options back and removes the copy")
        return out

    def close(self) -> dict:
        self.cancelled = True   # a run waiting for the Battle.net app must not start the game again afterwards
        closed = [pid for pid, p in list(self.launched.items()) if self._close(p)]
        self.waiting = None
        job = self.run
        if job is not None and job["thread"] is not None and job["thread"].is_alive():
            job["thread"].join(30)   # closing the game ends its loop; then the run can report what it collected
        launcher = battlenet.restore()   # also after a crashed server left the app pointing at a test map
        return {"closed": closed, "running": self.status()["running"], "launcher": launcher,
                **({"run": self.run_status()} if self.run else {})}


GAME = Game()
