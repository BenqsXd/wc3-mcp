"""World Editor driver. The editor is found by its process image and main window (class OsWindow with a menu bar);
the map, unsaved changes and busy state come from the window title and open dialogs. Maps and campaigns (.w3n, shown
in the Campaign Editor) are opened by launching the editor with -loadfile. Take-turns safety: anything that would lose
unsaved changes needs discard=true."""
import re
import subprocess
import time
from pathlib import Path

import win32gui

from .. import config
from ..errors import ToolError
from . import win

EXE_NAME = "World Editor.exe"
TITLE = re.compile(r"^Warcraft III World Editor(?: - \[(?P<doc>.*?)(?P<dirty> \*)?\])?$")
CAMPAIGN_TITLE = re.compile(r"^Campaign Editor - \[(?P<doc>.*?)(?P<dirty> \*)?\]$")
PALETTES = {"Tool Palette"}
# message boxes the editor shows for information during a save; they wait for a click and never close by themselves
NOTICES = {"Reminder"}
BENIGN = re.compile(r"Referencing unknown database field|Failed to load Environment Map")  # shipped data, every map
DISABLED = re.compile(r"Trigger '(?P<name>.*)' has been disabled due to errors")


def parse_title(title: str) -> dict | None:
    m = TITLE.match(title)
    if m is None:
        return None
    doc = m.group("doc")
    untitled = doc == "Untitled"
    return {"map": str(Path(doc.replace("/", "\\"))) if doc and not untitled else None, "untitled": untitled,
            "dirty": bool(m.group("dirty"))}


def editor_messages(lines: list[str]) -> dict:
    """The messages the editor shows in its viewport (SysMsg log lines): files it could not load, known-benign
    shipped-data lines (counted) and the rest."""
    messages = [line.split("SysMsg: ", 1)[1].strip() for line in lines if "SysMsg: " in line]
    missing = sorted({m.split("Could not load file: ", 1)[1] for m in messages if m.startswith("Could not load file: ")})
    rest = [m for m in messages if m and not m.startswith("Could not load file: ")]
    benign = [m for m in rest if BENIGN.search(m)]
    return {"missing_files": missing, "messages": [m for m in rest if not BENIGN.search(m)][-50:],
            "benign_messages": len(benign)}


def _same(a: str | None, b: str | None) -> bool:
    return bool(a and b) and a.lower() == b.lower()


def _shows(s: dict, target: Path) -> bool:
    """Whether the editor shows `target`: the map of the main window, or the campaign of the Campaign Editor (whose
    title abbreviates the folders)."""
    if target.suffix.lower() == ".w3n":
        return bool(s["campaign"]) and s["campaign"].replace("\\", "/").lower().endswith("/" + target.name.lower())
    return _same(s["map"], str(target))


def _unsaved(s: dict) -> str | None:
    if s["dirty"]:
        return s["map"] or "an untitled map"
    return f"the campaign {s['campaign'] or 'Untitled'}" if s["campaign_dirty"] else None


def _kill(pid: int) -> None:
    """End an editor that ignores its close message: a long operation (Calculate Shadows) owns the message loop."""
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)


class Editor:
    def __init__(self):
        self.launched: set[int] = set()

    # ---- discovery -------------------------------------------------------------------------------------------
    @staticmethod
    def exe() -> Path:
        return config.install_root() / "_retail_" / "x86_64" / EXE_NAME

    @staticmethod
    def _main_of(pid: int) -> int | None:
        return next((h for h in win.windows(pid) if win32gui.GetClassName(h) == "OsWindow" and win32gui.GetMenu(h)
                     and TITLE.match(win32gui.GetWindowText(h))), None)

    def status(self) -> dict:
        for pid in win.processes(EXE_NAME):
            main = self._main_of(pid)
            title = parse_title(win32gui.GetWindowText(main)) if main else None
            dialogs, modules = [], []
            for h in win.windows(pid):
                cls, name = win32gui.GetClassName(h), win32gui.GetWindowText(h)
                if cls == "#32770" and name not in PALETTES:
                    (modules if win32gui.GetMenu(h) else dialogs).append(name)
            campaign = next((m for m in map(CAMPAIGN_TITLE.match, modules) if m), None)
            return {"running": True, "pid": pid, "launched_by_server": pid in self.launched, "ready": main is not None,
                    "map": title["map"] if title else None, "untitled": bool(title and title["untitled"]),
                    "dirty": bool(title and title["dirty"]), "busy": "Progress" in dialogs, "dialogs": dialogs,
                    "modules": modules,
                    "campaign": campaign["doc"] if campaign and campaign["doc"] != "Untitled" else None,
                    "campaign_dirty": bool(campaign and campaign["dirty"])}
        return {"running": False, "pid": None, "launched_by_server": False, "ready": False, "map": None,
                "untitled": False, "dirty": False, "busy": False, "dialogs": [], "modules": [], "campaign": None,
                "campaign_dirty": False}

    def main(self) -> int:
        for pid in win.processes(EXE_NAME):
            main = self._main_of(pid)
            if main:
                return main
        raise ToolError("editor_not_running", "no World Editor is running", hint="editor_launch starts one")

    @property
    def pid(self) -> int | None:
        return self.status()["pid"]

    def find_window(self, title: str) -> int | None:
        pid = self.pid
        return next((h for h in win.windows(pid) if win32gui.GetWindowText(h) == title), None) if pid else None

    def wait_window(self, title: str, timeout: float = 20) -> int:
        end = time.time() + timeout
        while time.time() < end:
            h = self.find_window(title)
            if h:
                time.sleep(0.3)
                return h
            time.sleep(0.2)
        raise ToolError("timeout", f"no editor window titled {title!r} appeared within {timeout} s")

    # ---- lifecycle -------------------------------------------------------------------------------------------
    def launch(self, map_path=None, timeout: float = 120) -> dict:
        if win.processes(EXE_NAME):
            raise ToolError("editor_running", "a World Editor is already running",
                            hint="editor_status shows it; editor_map open switches maps")
        exe = self.exe()
        if not exe.is_file():
            raise ToolError("no_install", f"{exe} not found", hint="set WC3MCP_INSTALL")
        args, target = [str(exe), "-launch"], None
        if map_path:
            target = Path(map_path).resolve()
            if not target.exists():
                raise ToolError("not_found", f"no map at {target}")
            args += ["-loadfile", str(target)]
        process = subprocess.Popen(args, cwd=exe.parent)
        self.launched.add(process.pid)
        end = time.time() + timeout
        while time.time() < end:
            if process.poll() is not None:
                raise ToolError("launch_failed", f"the World Editor exited during start-up (code {process.returncode})")
            s = self.status()
            if s["ready"] and not s["busy"] and (_shows(s, target) if target else s["untitled"]):
                time.sleep(1.0)
                return self.status()
            time.sleep(0.5)
        raise ToolError("timeout", f"the World Editor was not ready after {timeout} s", status=self.status())

    def _loaded(self) -> dict:
        s = self.status()
        if not s["running"]:
            raise ToolError("editor_not_running", "no World Editor is running", hint="editor_launch starts one")
        if s["dialogs"]:
            raise ToolError("dialog_open", f"the editor is showing {s['dialogs']}",
                            hint="editor_dialogs shows them; editor_dialog_act answers them")
        return s

    def open(self, map_path, discard: bool = False, timeout: float = 120) -> dict:
        """Show `map_path` in the editor. `previous_instance` says what happened to the editor that was running:
        reused (it already showed this map), relaunched (it was quit and started again) or none."""
        target = Path(map_path).resolve()
        if not target.exists():
            raise ToolError("not_found", f"no map at {target}")
        s = self.status()
        previous = "none"
        if s["running"]:
            if _shows(s, target) and not _unsaved(s):
                return {**s, "previous_instance": "reused"}
            if _unsaved(s) and not discard:
                raise ToolError("unsaved_changes", f"the editor has unsaved changes in {_unsaved(s)}",
                                hint="save them (editor_map save / save_campaign) or ask the user; discard=true drops them")
            self.quit(discard=discard)
            previous = "relaunched"
        return {**self.launch(target, timeout), "previous_instance": previous}

    def reload(self, discard: bool = False) -> dict:
        s = self._loaded()
        if not s["map"]:
            raise ToolError("no_map", "the editor has no saved map open")
        return self.open(s["map"], discard=True) if discard or not s["dirty"] else self.open(s["map"])

    def _answer_prompt(self, answer: str) -> bool:
        """Answer a 'Save changes to ...?' prompt if one is showing; returns whether one was answered."""
        h = self.find_window("Warning")
        if not h:
            return False
        controls = win.controls(h)
        if not any("Save changes" in c["text"] for c in controls):
            return False
        win.click(next(c["hwnd"] for c in controls if c["class"] == "Button" and c["text"].replace("&", "") == answer))
        return True

    def close(self, discard: bool = False, timeout: float = 60) -> dict:
        s = self._loaded()
        if not (s["map"] or s["untitled"]):
            return s
        if s["dirty"] and not discard:
            raise ToolError("unsaved_changes", f"the editor has unsaved changes in {s['map'] or 'an untitled map'}",
                            hint="save them (editor_map save) or ask the user; discard=true drops them")
        main = self.main()
        win.post_command(main, win.find_command(win.window_menu(main), "File/Close Map"))
        end = time.time() + timeout
        while time.time() < end:
            self._answer_prompt("No")
            s = self.status()
            if not (s["map"] or s["untitled"]) and not s["dialogs"]:
                return s
            time.sleep(0.3)
        raise ToolError("timeout", "the map did not close", status=self.status())

    def quit(self, discard: bool = False, timeout: float = 60, force: bool = False) -> dict:
        s = self.status()
        if not s["running"]:
            return s
        if _unsaved(s) and not discard:
            raise ToolError("unsaved_changes", f"the editor has unsaved changes in {_unsaved(s)}",
                            hint="save them (editor_map save / save_campaign) or ask the user; discard=true drops them")
        pid = s["pid"]
        if discard:
            self._dismiss_errors()
        win.close(self.main())
        end = time.time() + timeout
        while time.time() < end:
            if not win.running(pid):
                self.launched.discard(pid)
                return self.status()
            self._answer_prompt("No")
            time.sleep(0.3)
        if force:
            _kill(pid)
            self.launched.discard(pid)
            return {**self.status(), "killed": True}
        raise ToolError("timeout", "the World Editor did not exit", hint="it may be busy or showing a dialog "
                        "(a progress dialog such as Calculate Shadows cannot be cancelled from here): "
                        "editor_map action=quit force=true ends the process", status=self.status())

    # ---- saving ----------------------------------------------------------------------------------------------
    def _dismiss_notices(self) -> list[str]:
        """Read and close the editor's informational message boxes, which a save otherwise waits for forever: a map
        still named "Just another Warcraft III map" gets a Reminder box every time it is saved. Their text is
        reported as messages."""
        out = []
        for title in NOTICES:
            h = self.find_window(title)
            if not h:
                continue
            controls = win.controls(h)
            out += [c["text"] for c in controls if c["class"] == "Static" and c["text"] and c["visible"]]
            button = next((c for c in controls if c["class"] == "Button" and c["id"] in (1, 2)), None) \
                or next((c for c in controls if c["class"] == "Button"), None)
            if button:
                win.click(button["hwnd"])
                time.sleep(0.5)
        return out

    def _dismiss_errors(self) -> tuple[list[dict], list[str], list[str]]:
        """Read and close the editor's compile error dialogs: (errors, disabled triggers, other messages)."""
        errors, disabled, messages = [], [], []
        for title in ("Error", "Script Errors"):
            h = self.find_window(title)
            if not h:
                continue
            controls = win.controls(h)
            statics = [c["text"] for c in controls if c["class"] == "Static" and c["text"] and c["visible"]]
            if title == "Error":
                for text in statics:
                    m = DISABLED.search(text)
                    (disabled.append(m["name"]) if m else messages.append(text))
                button = next((c for c in controls if c["class"] == "Button"), None)
            else:  # visible statics: trigger name or generated script path, "<n> compile error(s)", "Line:", line
                paths = [s for s in statics if "/" in s or "\\" in s]
                names = [s for s in statics if s not in paths and "compile error" not in s and s != "Line:"
                         and not s.isdigit()]
                line = next((statics[i + 1] for i, s in enumerate(statics[:-1]) if s == "Line:"), None)
                for c in controls:
                    if c["class"] == "ListBox":
                        errors += [{"trigger": names[0] if names else None, "message": item, "line": line,
                                    "script": paths[0] if paths else None} for item in c.get("items", [])]
                button = next((c for c in controls if c["class"] == "Button" and c["id"] == 10), None)
            if button:
                win.click(button["hwnd"])
                time.sleep(0.5)
        return errors, disabled, messages

    def save(self, timeout: float = 300) -> dict:
        """File > Save Map. The editor regenerates the script on save; script errors come back in `errors` and the
        editor disables the failing triggers (the map stays unsaved and dirty)."""
        s = self._loaded()
        if not s["map"]:
            raise ToolError("no_map", "the editor has no saved map open" if not s["untitled"] else
                            "this map was never saved; use editor_menu File/Save Map As...")
        target = Path(s["map"])
        mtime = target.stat().st_mtime if target.exists() else None
        main = self.main()
        win.post_command(main, win.find_command(win.window_menu(main), "File/Save Map"))
        errors, disabled, messages = [], [], []
        end, quiet_since = time.time() + timeout, None
        while time.time() < end:
            s = self.status()
            if "Error" in s["dialogs"] or "Script Errors" in s["dialogs"]:
                time.sleep(0.8)  # both error dialogs appear within a second
                e, d, m = self._dismiss_errors()
                errors, disabled, messages = errors + e, disabled + d, messages + m
                quiet_since = None
            elif NOTICES & set(s["dialogs"]):
                messages += self._dismiss_notices()   # a notice box waits for a click, not for the save
                quiet_since = None
            elif s["dialogs"]:
                quiet_since = None
            else:
                quiet_since = quiet_since or time.time()
                written = target.exists() and target.stat().st_mtime != mtime
                if time.time() - quiet_since > (0.5 if written and not s["dirty"] else 2.0):
                    break
            time.sleep(0.3)
        else:
            raise ToolError("timeout", f"saving did not finish within {timeout} s", status=self.status())
        written = target.exists() and target.stat().st_mtime != mtime
        for error in errors:  # the dialog may name the generated script instead of the trigger
            if error["trigger"] is None and len(set(disabled)) == 1:
                error["trigger"] = disabled[0]
        s = self.status()
        return {"saved": written and not errors, "errors": errors, "disabled_triggers": disabled, "messages": messages,
                "dirty": s["dirty"], "map": s["map"]}

    def save_campaign(self, timeout: float = 120) -> dict:
        """Campaign Editor > Save Campaign. The editor asks before saving a campaign whose maps have no button; the
        save goes ahead and the question comes back in `warnings`."""
        s = self._loaded()
        title = next((m for m in s["modules"] if CAMPAIGN_TITLE.match(m)), None)
        if title is None or not s["campaign"]:
            raise ToolError("no_campaign", "the Campaign Editor shows no saved campaign",
                            hint="editor_map open with a .w3n map_path opens one")
        was_dirty = s["campaign_dirty"]
        # menu commands posted to the Campaign Editor are ignored unless it is the active window: use its shortcut
        win.send_input(self.find_window(title), [{"keys": "ctrl+s"}])
        warnings, end, quiet_since = [], time.time() + timeout, None
        while time.time() < end:
            h = self.find_window("Warning")
            if h:
                text = " ".join(c["text"] for c in win.controls(h) if c["class"] == "Static" and c["text"])
                if "Continue with save" not in text:
                    raise ToolError("dialog_open", f"the editor asks: {text}", hint="editor_dialogs shows it")
                warnings.append(text)
                win.send_input(h, [{"keys": "enter"}])   # BM_CLICK leaves this message box open
                quiet_since = None
            s = self.status()
            if s["dialogs"] or s["campaign_dirty"]:
                quiet_since = None
            else:
                quiet_since = quiet_since or time.time()
                if time.time() - quiet_since > (0.5 if was_dirty else 2.0):
                    break
            time.sleep(0.3)
        else:
            raise ToolError("timeout", f"saving the campaign did not finish within {timeout} s", status=self.status())
        return {"saved": not s["campaign_dirty"], "warnings": warnings, "campaign": s["campaign"]}

    def compile(self, timeout: float = 300) -> dict:
        """Save through the editor to regenerate and check the map script (JassHelper for JASS maps)."""
        return self.save(timeout)

    # ---- UI access -------------------------------------------------------------------------------------------
    def _window(self, title: str | None) -> int:
        if title in (None, "", "main"):
            return self.main()
        h = self.find_window(title)
        if h is None:
            s = self.status()
            raise ToolError("no_window", f"no editor window titled {title!r}",
                            hint="editor_status lists dialogs and modules", choices=s["dialogs"] + s["modules"])
        return h

    def menu(self, window: str | None = None) -> list[dict]:
        tree = win.window_menu(self._window(window))
        if not tree:
            raise ToolError("no_menu", f"{window or 'the main window'} has no menu bar")
        return tree

    def invoke(self, path: str, window: str | None = None) -> dict:
        h = self._window(window)
        win.post_command(h, win.find_command(win.window_menu(h), path))
        time.sleep(0.5)
        return self.status()

    @staticmethod
    def _snapshot(h: int) -> list[dict]:
        return [{k: v for k, v in c.items() if k not in ("hwnd", "visible")} for c in win.controls(h) if c["visible"]]

    def dialogs(self, include_palettes: bool = False) -> list[dict]:
        pid = self.status()["pid"]
        if pid is None:
            raise ToolError("editor_not_running", "no World Editor is running", hint="editor_launch starts one")
        return [{"title": win32gui.GetWindowText(h), "controls": self._snapshot(h)} for h in win.windows(pid)
                if win32gui.GetClassName(h) == "#32770" and not win32gui.GetMenu(h)
                and (include_palettes or win32gui.GetWindowText(h) not in PALETTES)]

    def dialog_act(self, dialog: str, actions: list[dict]) -> dict:
        h = self.find_window(dialog)
        if h is None or win32gui.GetClassName(h) != "#32770":
            raise ToolError("no_dialog", f"no editor dialog titled {dialog!r}", hint="editor_dialogs lists them",
                            choices=self.status()["dialogs"])
        if not isinstance(actions, list):
            raise ToolError("bad_op", "actions must be a list", hint='[{"control": 14, "set_text": "My Map"}, '
                                                                     '{"control": "OK", "click": true}]')
        for i, action in enumerate(actions):
            if not isinstance(action, dict) or "control" not in action:
                raise ToolError("bad_op", f"actions[{i}] needs a control (id or text)")
            controls = [c for c in win.controls(h) if c["visible"]]
            key = action["control"]
            control = next((c for c in controls if (c["id"] == key if isinstance(key, int) else
                                                    c["text"].replace("&", "").strip().lower() == str(key).lower())), None)
            if control is None:
                raise ToolError("no_control", f"actions[{i}]: no control {key!r} in {dialog!r}", op_index=i,
                                choices=[c["text"] or c["id"] for c in controls][:60])
            if not control["enabled"]:  # clicking a disabled radio button with nothing behind it crashes the editor
                raise ToolError("control_disabled", f"actions[{i}]: control {key!r} in {dialog!r} is disabled",
                                hint="change what enables it first (editor_dialogs shows enabled states)", op_index=i)
            if "set_text" in action:
                win.set_text(control["hwnd"], str(action["set_text"]))
            elif action.get("click"):
                win.click(control["hwnd"])
            elif "check" in action:
                win.check(control["hwnd"], bool(action["check"]))
            elif "select" in action:
                win.select(control["hwnd"], action["select"])
            else:
                raise ToolError("bad_op", f"actions[{i}]: expected set_text, click, check or select", op_index=i)
            time.sleep(0.2)
        time.sleep(0.5)
        if not (win32gui.IsWindow(h) and win32gui.IsWindowVisible(h)):
            return {"title": dialog, "closed": True, "status": self.status()}
        return {"title": dialog, "closed": False, "controls": self._snapshot(h)}

    def input(self, window: str | None, actions: list[dict]) -> dict:
        win.send_input(self._window(window), actions)
        return self.status()

    def screenshot(self, target: str | None = "main", region: list[int] | None = None) -> bytes:
        return win.screenshot(self._window(target), region)

    @staticmethod
    def log(lines: int = 200) -> dict:
        path = config.documents() / "Logs" / "War3EditorLog.txt"
        text = path.read_text("utf-8", "replace").splitlines() if path.exists() else []
        folder = config.documents() / "Errors"
        crashes = sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime,
                         reverse=True)[:5] if folder.is_dir() else []
        result = {"log": text[-lines:], **editor_messages(text),
                  "written": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime)) if text else None,
                  "crashes": [{"folder": p.name, "files": sorted(f.name for f in p.iterdir())} for p in crashes]}
        if win.processes(EXE_NAME):
            result["note"] = ("the World Editor writes this log only when it quits, so this is its previous session; "
                              "map_validate reports placed objects without a model right away")
        return result


EDITOR = Editor()
