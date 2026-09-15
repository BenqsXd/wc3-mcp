"""Script validation. JASS: pjass (plain JASS) or JassHelper --scriptonly (vJASS, then pjass), both run from a copy of
the install's JassHelper folder. Lua: the pure-Python Lua 5.3 syntax checker. Errors carry the editor section and
trigger their line falls in when the script was written by the World Editor."""
import bisect
import ctypes
import re
import shutil
import subprocess
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

from .. import config, pathguard
from ..errors import ToolError
from . import luacheck

BAR = "//" + "=" * 75
PJASS_ERR = re.compile(r"^(.*?):(\d+): (.*)$")  # <file>:<line>: <message>
JH_ERR = re.compile(r"^Line (\d+): +(.*)$")      # logs\compileerrors.txt entries
VJASS = re.compile(r"(?m)^[ \t]*(?:(?:library|library_once|scope|struct|interface|module|textmacro)\b|//!)")
TOOL_FILES = ("pjass.exe", "jasshelper.exe", "jasshelper.conf", "sfmpq.dll")
_ready: set[Path] = set()


def tool_dir(catalog) -> Path:
    """A writable copy of the install's JassHelper folder plus this build's common.j and Blizzard.j."""
    target = config.home() / "tools" / "jasshelper"
    if target in _ready:
        return target
    pathguard.ensure_writable(target)
    source = config.install_root() / "_retail_" / "x86_64" / "JassHelper"
    target.mkdir(parents=True, exist_ok=True)
    for name in TOOL_FILES:
        src, dst = source / name, target / name
        if not src.is_file():
            raise ToolError("no_tools", f"{src} not found", hint="the Warcraft III install ships JassHelper there")
        if not dst.is_file() or dst.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dst)
    for rel in ("Scripts/common.j", "Scripts/Blizzard.j"):
        data = catalog._read(rel)
        if data is None:
            raise ToolError("no_tools", f"{rel} is missing from the game data")
        dst = target / rel.split("/")[1]
        if not dst.is_file() or dst.read_bytes() != data:
            dst.write_bytes(data)
    _ready.add(target)
    return target


def is_vjass(text: str) -> bool:
    return VJASS.search(text) is not None


def _err(line, message, **extra):
    return {"line": line, "message": message, "section": None, "trigger": None, "source": None, **extra}


def section_index(script_text):
    """[(first_line, banner_title, trigger_name|None)] sorted by line, for an editor-generated script."""
    marks, title, prev = [(1, None, None)], None, ""
    for i, line in enumerate(script_text.splitlines(), 1):
        if prev == "//*" and line.startswith("//*  "):
            title = line[5:].strip()
            marks.append((max(i - 2, 1), title, None))
        elif prev == BAR and line.startswith("// Trigger: "):
            marks.append((i - 1, title, line[len("// Trigger: "):]))
        elif prev == BAR and line.startswith("function InitCustomTriggers "):
            marks.append((i - 1, title, None))
        prev = line
    return marks


def _locate(script_text, errors):
    marks, lines = section_index(script_text), script_text.splitlines()
    starts = [m[0] for m in marks]
    for e in errors:
        if e["line"] and e.get("file") is None:
            _, e["section"], e["trigger"] = marks[bisect.bisect_right(starts, e["line"]) - 1]
            e["source"] = lines[e["line"] - 1].strip() if e["line"] <= len(lines) else None
    return errors


def _pjass(script_text, tools: Path, timeout):
    exe = str(tools / "pjass.exe")
    r = subprocess.run([exe, str(tools / "common.j"), str(tools / "Blizzard.j"), "-"],
                       input=script_text.encode("utf-8", "surrogateescape"), capture_output=True, timeout=timeout)
    out, errors = r.stdout.decode("utf-8", "replace"), []
    for line in out.splitlines():
        m = PJASS_ERR.match(line)
        if m:  # errors inside common.j / Blizzard.j keep their file name
            errors.append(_err(int(m[2]), m[3].strip(), file=None if m[1] == "<stdin>" else m[1]))
        elif line.startswith("Error: "):
            errors.append(_err(None, line[7:], file=None))
    if r.returncode and not errors:
        errors.append(_err(None, out.strip()[-500:] or f"pjass exit {r.returncode}", file=None))
    version = subprocess.run([exe, "-v"], capture_output=True, timeout=timeout).stdout.decode("utf-8", "replace").split()
    return {"ok": r.returncode == 0, "errors": _locate(script_text, errors),
            "tool": "pjass " + version[-1] if version else "pjass"}


class _Process(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("pid", wintypes.DWORD),
                ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                ("ppid", wintypes.DWORD), ("pri", ctypes.c_long), ("flags", wintypes.DWORD),
                ("exe", ctypes.c_wchar * 260)]


def _children(pid):
    k32 = ctypes.WinDLL("kernel32")
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Process)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap, e, out = k32.CreateToolhelp32Snapshot(2, 0), _Process(), []  # TH32CS_SNAPPROCESS
    e.dwSize = ctypes.sizeof(e)
    ok = k32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        if e.ppid == pid:
            out.append(e.pid)
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return out


def _jasshelper(script_text, tools: Path, timeout):
    name = "jasshelper --scriptonly"
    (tools / "work").mkdir(exist_ok=True)
    # JassHelper writes logs\ and backups\ into its working directory: a fresh cwd per run keeps runs independent
    with tempfile.TemporaryDirectory(dir=tools / "work", ignore_cleanup_errors=True) as tmp:
        cwd = Path(tmp)
        inp, outp = cwd / "input.j", cwd / "output.j"
        inp.write_bytes(script_text.encode("utf-8", "surrogateescape"))
        p = subprocess.Popen([str(tools / "jasshelper.exe"), "--scriptonly", str(tools / "common.j"),
                              str(tools / "Blizzard.j"), str(inp), str(outp)],
                             cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            p.wait(timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        # on errors JassHelper starts "jasshelper.exe --showerrors", a window that waits for OK: kill it
        for _ in range(10):
            kids = _children(p.pid)
            for pid in kids:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=30)
            if kids or p.returncode == 0:
                break
            time.sleep(0.1)
        result = {"ok": p.returncode == 0 and outp.exists(), "errors": [], "tool": name}
        errs = cwd / "logs" / "compileerrors.txt"
        if result["ok"]:
            result["output"] = outp.read_bytes().decode("utf-8", "replace")
        elif errs.exists():
            # line 1: script the line numbers refer to (logs\currentmapscript.j, the preprocessed input);
            # line 2: stage ("pjass.exe" or "JASSHelper - Step N (...)"); then "Line N: message" entries
            lines = errs.read_text("utf-8", "replace").splitlines()
            result["errors"] = [_err(int(m[1]), m[2].strip(), stage=lines[1]) for m in map(JH_ERR.match, lines[2:]) if m]
            ref = cwd / lines[0]
            if ref.is_file():
                _locate(ref.read_bytes().decode("utf-8", "replace"), result["errors"])
        if not result["ok"] and not result["errors"]:
            result["errors"].append(_err(None, f"jasshelper exit {p.returncode}"))
    return result


def validate_jass(text: str, catalog, vjass: bool | None = None, timeout: int = 60) -> dict:
    tools = tool_dir(catalog)
    started = time.perf_counter()
    try:
        result = (_jasshelper if (is_vjass(text) if vjass is None else vjass) else _pjass)(text, tools, timeout)
    except subprocess.TimeoutExpired as e:
        raise ToolError("timeout", f"script validation took longer than {timeout} s") from e
    result["seconds"] = round(time.perf_counter() - started, 3)
    return result


def validate_lua(text: str) -> dict:
    started = time.perf_counter()
    lines = text.splitlines()
    errors = [_err(e["line"], e["message"], column=e["column"],
                   source=lines[e["line"] - 1].strip() if e["line"] <= len(lines) else None)
              for e in luacheck.check(text)]
    return {"ok": not errors, "errors": errors, "tool": "luacheck", "seconds": round(time.perf_counter() - started, 3)}
