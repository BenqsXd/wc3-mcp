"""Starting Warcraft III through the Battle.net desktop app, which hands the game the app's own signed-in session.

A game started directly ("Warcraft III.exe -launch -loadfile ...") carries no session: it shows the Battle.net login
panel until somebody types a password there, and signing the app in does not change that. The app starts the game as
"-launch -uid w3" and the game takes its session from the app over the app's own channel, so a run started through
the app never meets the login panel. Nothing here reads, types or stores credentials.

The app appends "-launch -uid w3" to the arguments stored for the game in Battle.net.config under
Games.w3.AdditionalLaunchArguments ("Additional command line arguments" in its Game Settings). It reads that file
when it starts and overwrites it from memory while it runs, so arguments only take effect after the app is started
again - which is why `configure` stops the app before it writes them.
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .. import config
from . import win

UID, PRODUCT = "w3", "W3"
APP_NAME = "Battle.net.exe"
LAUNCH_TIMEOUT = 180     # from "launch W3" to a game process (the app may start, sign in or patch the game first)
ASK_AGAIN = 25           # an app that is still starting ignores the command: ask again this often
# the map every run through the app is launched on: the arguments then never change, so the app keeps running
LAUNCH_COPY = "map.w3x"


def exe() -> Path | None:
    """The Battle.net desktop app."""
    for candidate in (os.environ.get("WC3MCP_BATTLENET"),
                      os.path.expandvars(r"%ProgramFiles(x86)%\Battle.net\Battle.net.exe"),
                      os.path.expandvars(r"%ProgramFiles%\Battle.net\Battle.net.exe")):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def config_path() -> Path:
    return Path(os.environ["APPDATA"]) / "Battle.net" / "Battle.net.config"


def launch_copy() -> Path:
    """Where a run puts the map it asks the app to launch: one path, so the stored arguments stay the same."""
    return config.home() / "launch" / LAUNCH_COPY


def game_args(target: Path) -> str:
    return f'-loadfile "{target}" -windowmode windowed -nowfpause'


def stored_args() -> str:
    """What the app launches Warcraft III with today (its own Game Settings field)."""
    try:
        data = json.loads(config_path().read_text("utf-8"))
    except (OSError, ValueError):
        return ""
    return data.get("Games", {}).get(UID, {}).get("AdditionalLaunchArguments", "")


def processes() -> list[int]:
    """Running Battle.net app processes. The app's own processes refuse the handle win.processes() opens, so this
    asks Windows for the list instead."""
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {APP_NAME}", "/NH", "/FO", "CSV"],
                         capture_output=True, text=True, check=False)
    return [int(row.split('","')[1]) for row in out.stdout.splitlines() if row.startswith('"')]


def _stop() -> None:
    subprocess.run(["taskkill", "/IM", APP_NAME, "/F"], capture_output=True, check=False)
    for _ in range(20):
        if not processes():
            return
        time.sleep(1)


def _start(app: Path) -> None:
    subprocess.Popen([str(app)])
    deadline = time.time() + 30
    while time.time() < deadline and not processes():
        time.sleep(1)


def configure(app: Path, target: Path) -> dict:
    """Make the app launch Warcraft III on `target`, restarting it when its stored arguments differ. Returns what
    was done, including the arguments it replaced (kept in the server's home folder, since the app drops keys it
    does not know)."""
    wanted, before = game_args(target), stored_args()
    if before == wanted:
        return {"restarted": False, "args": wanted}
    _stop()
    if before and before != wanted:
        kept = config.home() / "battlenet-previous-launch-arguments.txt"
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_text(before, encoding="utf-8")
    path = config_path()
    data = json.loads(path.read_text("utf-8")) if path.is_file() else {}
    data.setdefault("Games", {}).setdefault(UID, {})["AdditionalLaunchArguments"] = wanted
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    _start(app)
    return {"restarted": True, "args": wanted, **({"replaced": before} if before else {})}


def copy_map(source: Path) -> Path:
    """The map the app launches lives at one path, so the app's stored arguments never change."""
    target = launch_copy()
    target.parent.mkdir(parents=True, exist_ok=True)
    if source != target:
        shutil.copyfile(source, target)
    return target


def forget_map() -> None:
    """Remove the launch copy once a run is over: a Play in the Battle.net app then opens the menu, not the map."""
    try:
        launch_copy().unlink(missing_ok=True)
    except OSError:
        pass   # a game still holds it; the next run overwrites it


def launch(app: Path, game_name: str, running_before: set[int] | None = None) -> tuple[int | None, dict]:
    """Ask the app to start Warcraft III and return the new game's pid (None when none appeared in time). An app
    that has just started ignores the command until it is ready, so the command is repeated while waiting."""
    before = set(win.processes(game_name)) if running_before is None else running_before
    start, asked_at = time.time(), -ASK_AGAIN
    while time.time() - start < LAUNCH_TIMEOUT:
        if time.time() - asked_at >= ASK_AGAIN:
            asked_at = time.time()
            subprocess.Popen([str(app), f"--exec=launch {PRODUCT}"])
        time.sleep(2)
        fresh = [pid for pid in win.processes(game_name) if pid not in before]
        if fresh:
            return fresh[0], {"ok": True, "seconds": round(time.time() - start, 1)}
    return None, {"ok": False, "seconds": round(time.time() - start, 1),
                  "reason": (f"the Battle.net app did not start the game within {LAUNCH_TIMEOUT:g} s: it may be "
                             "updating itself or the game, or waiting for its own login - ask the user to open it "
                             "and log in once with 'Keep me logged in'")}
