"""Win32 helpers: processes, windows, controls, runtime menus, window messages, input and screenshots.
Messages that wait for a reply use SendMessageTimeout so a hung application cannot hang the server."""
import ctypes
import io
import time
from contextlib import contextmanager
from ctypes import wintypes

import win32api
import win32con
import win32gui
import win32process
from PIL import ImageGrab

from ..errors import ToolError

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.GetSubMenu.restype = wintypes.HMENU
user32.GetSubMenu.argtypes = [wintypes.HMENU, ctypes.c_int]
user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
user32.GetMenuItemID.restype = wintypes.UINT
user32.GetMenuItemID.argtypes = [wintypes.HMENU, ctypes.c_int]
user32.GetMenuState.restype = wintypes.UINT
user32.GetMenuState.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
user32.GetMenuStringW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.LPWSTR, ctypes.c_int, wintypes.UINT]
user32.SendMessageTimeoutW.restype = wintypes.LPARAM
user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT,
                                       wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

KEYS = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "enter": 0x0D, "return": 0x0D,
        "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
        "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "left": 0x25, "up": 0x26,
        "right": 0x27, "down": 0x28, **{f"f{i}": 0x6F + i for i in range(1, 13)}}
CHECKABLE = {2, 3, 4, 5, 6, 9}  # BS_CHECKBOX, BS_AUTOCHECKBOX, BS_RADIOBUTTON, BS_3STATE, BS_AUTO3STATE, BS_AUTORADIOBUTTON
MOUSE = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}


# ---- menus -----------------------------------------------------------------------------------------------------
def menu_label(text: str) -> str:
    return text.split("\t", 1)[0].replace("&", "").strip()


def menu_tree(hmenu, depth: int = 0) -> list[dict]:
    items = []
    for i in range(user32.GetMenuItemCount(hmenu)):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetMenuStringW(hmenu, i, buf, 256, win32con.MF_BYPOSITION)
        label = menu_label(buf.value)
        if not label:
            continue  # separator
        sub = user32.GetSubMenu(hmenu, i)
        if sub and depth < 6:
            items.append({"label": label, "id": None, "items": menu_tree(sub, depth + 1)})
        else:
            state = user32.GetMenuState(hmenu, i, win32con.MF_BYPOSITION)
            items.append({"label": label, "id": user32.GetMenuItemID(hmenu, i),
                          "enabled": not state & (win32con.MF_GRAYED | win32con.MF_DISABLED),
                          "checked": bool(state & win32con.MF_CHECKED)})
    return items


def window_menu(hwnd: int) -> list[dict]:
    hmenu = win32gui.GetMenu(hwnd)
    return menu_tree(hmenu) if hmenu else []


def find_command(tree: list[dict], path: str) -> int:
    parts = [p.strip().lower() for p in path.split("/") if p.strip()]
    items, trail = tree, []
    for depth, part in enumerate(parts):
        match = next((it for it in items if it["label"].lower() == part), None)
        if match is None:
            raise ToolError("no_menu_item", f"no menu item {part!r} under {'/'.join(trail) or 'the menu bar'}",
                            hint="list the menus to see the labels", choices=[it["label"] for it in items])
        trail.append(match["label"])
        last = depth == len(parts) - 1
        if last and "items" in match:
            raise ToolError("no_menu_item", f"{'/'.join(trail)} is a submenu, not a command",
                            choices=[it["label"] for it in match["items"]])
        if last:
            return match["id"]
        if "items" not in match:
            raise ToolError("no_menu_item", f"{'/'.join(trail)} is a command, not a submenu")
        items = match["items"]
    raise ToolError("no_menu_item", "empty menu path", choices=[it["label"] for it in tree])


def parse_keys(chord: str) -> list[int]:
    codes = []
    for part in chord.lower().split("+"):
        part = part.strip()
        if part in KEYS:
            codes.append(KEYS[part])
        elif len(part) == 1 and part.isalnum():
            codes.append(ord(part.upper()))
        else:
            raise ToolError("bad_value", f"unknown key {part!r}",
                            hint="use names like ctrl, shift, alt, enter, esc, f4, or single letters and digits")
    return codes


# ---- processes and windows -------------------------------------------------------------------------------------
def image(pid: int) -> str:
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        return buf.value if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) else ""
    finally:
        kernel32.CloseHandle(handle)


def processes(image_name: str) -> list[int]:
    """Running processes of an image. Exited ones stay listed while a handle is open (subprocess keeps one for a
    child it launched), so they are left out."""
    name = image_name.lower()
    return [pid for pid in win32process.EnumProcesses()
            if pid and image(pid).rsplit("\\", 1)[-1].lower() == name and running(pid)]


def running(pid: int) -> bool:
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def owner(hwnd: int) -> dict:
    """Who a window belongs to: the process's exe name, the window title and the pid."""
    pid = win32process.GetWindowThreadProcessId(hwnd)[1]
    return {"exe": image(pid).rsplit("\\", 1)[-1], "title": win32gui.GetWindowText(hwnd), "pid": pid}


def minimize(hwnd: int) -> None:
    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)


def windows(pid: int, visible_only: bool = True) -> list[int]:
    found = []

    def cb(h, _):
        if win32process.GetWindowThreadProcessId(h)[1] == pid and (not visible_only or win32gui.IsWindowVisible(h)):
            found.append(h)
        return True

    win32gui.EnumWindows(cb, None)
    return found


def info(hwnd: int) -> dict:
    return {"hwnd": hwnd, "class": win32gui.GetClassName(hwnd), "title": win32gui.GetWindowText(hwnd),
            "rect": list(win32gui.GetWindowRect(hwnd)), "visible": bool(win32gui.IsWindowVisible(hwnd)),
            "enabled": bool(win32gui.IsWindowEnabled(hwnd))}


# ---- controls --------------------------------------------------------------------------------------------------
def _send(hwnd: int, msg: int, wparam=0, lparam=0) -> int:
    result = ctypes.c_size_t()
    if not user32.SendMessageTimeoutW(hwnd, msg, wparam, lparam, 0x0002, 3000, ctypes.byref(result)):  # SMTO_ABORTIFHUNG
        raise ToolError("not_responding", "the window did not answer within 3 s", hint="check editor_status")
    return result.value


def get_text(hwnd: int) -> str:
    length = _send(hwnd, win32con.WM_GETTEXTLENGTH)
    buf = ctypes.create_unicode_buffer(length + 1)
    _send(hwnd, win32con.WM_GETTEXT, length + 1, ctypes.addressof(buf))
    return buf.value


def _items(hwnd: int, count_msg: int, len_msg: int, text_msg: int, limit: int = 200) -> list[str]:
    out = []
    for i in range(min(_send(hwnd, count_msg), limit)):
        n = _send(hwnd, len_msg, i)
        if n > 4096:
            break
        buf = ctypes.create_unicode_buffer(n + 1)
        _send(hwnd, text_msg, i, ctypes.addressof(buf))
        out.append(buf.value)
    return out


def items(hwnd: int) -> list[str]:
    cls = win32gui.GetClassName(hwnd)
    if cls == "ListBox":
        return _items(hwnd, win32con.LB_GETCOUNT, win32con.LB_GETTEXTLEN, win32con.LB_GETTEXT)
    if cls == "ComboBox":
        return _items(hwnd, win32con.CB_GETCOUNT, win32con.CB_GETLBTEXTLEN, win32con.CB_GETLBTEXT)
    return []


def controls(dialog: int) -> list[dict]:
    found = []

    def cb(c, _):
        try:
            entry = {"hwnd": c, "class": win32gui.GetClassName(c), "id": win32gui.GetDlgCtrlID(c),
                     "text": get_text(c)[:500], "visible": bool(win32gui.IsWindowVisible(c)),
                     "enabled": bool(win32gui.IsWindowEnabled(c))}
            if entry["class"] == "Button" and win32gui.GetWindowLong(c, win32con.GWL_STYLE) & 0xF in CHECKABLE:
                entry["checked"] = _send(c, win32con.BM_GETCHECK) == 1
            if entry["class"] in ("ListBox", "ComboBox"):
                entry["items"] = items(c)
                entry["selected"] = _send(c, win32con.LB_GETCURSEL if entry["class"] == "ListBox" else win32con.CB_GETCURSEL)
            found.append(entry)
        except (win32gui.error, ToolError):  # the control vanished or stopped answering while being read
            pass
        return True

    try:
        win32gui.EnumChildWindows(dialog, cb, None)
    except win32gui.error:
        pass
    return found


def set_text(hwnd: int, text: str) -> None:
    buf = ctypes.create_unicode_buffer(text)
    _send(hwnd, win32con.WM_SETTEXT, 0, ctypes.addressof(buf))


def click(hwnd: int) -> None:
    win32gui.PostMessage(hwnd, win32con.BM_CLICK, 0, 0)


def check(hwnd: int, state: bool) -> None:
    if (_send(hwnd, win32con.BM_GETCHECK) == 1) != state:
        click(hwnd)


def select(hwnd: int, value) -> None:
    cls = win32gui.GetClassName(hwnd)
    if cls not in ("ListBox", "ComboBox"):
        raise ToolError("bad_value", f"a {cls} control has no items to select")
    choices = items(hwnd)
    index = value if isinstance(value, int) else next((i for i, s in enumerate(choices) if s == value), -1)
    if not 0 <= index < len(choices):
        raise ToolError("no_item", f"{value!r} is not an item of this list", choices=choices[:50])
    listbox = cls == "ListBox"
    _send(hwnd, win32con.LB_SETCURSEL if listbox else win32con.CB_SETCURSEL, index)
    notify = win32api.MAKELONG(win32gui.GetDlgCtrlID(hwnd), 1)  # LBN_SELCHANGE / CBN_SELCHANGE
    win32gui.PostMessage(win32gui.GetParent(hwnd), win32con.WM_COMMAND, notify, hwnd)


def post_command(hwnd: int, command_id: int) -> None:
    win32gui.PostMessage(hwnd, win32con.WM_COMMAND, command_id, 0)


def close(hwnd: int) -> None:
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)


# ---- foreground, screenshots, input ----------------------------------------------------------------------------
def activate(hwnd: int) -> None:
    fg = win32gui.GetForegroundWindow()
    ours = win32api.GetCurrentThreadId()
    theirs = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
    attached = bool(theirs and theirs != ours and user32.AttachThreadInput(ours, theirs, True))
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except win32gui.error:
        pass
    finally:
        if attached:
            user32.AttachThreadInput(ours, theirs, False)


@contextmanager
def foreground(hwnd: int):
    """Bring `hwnd` to the front for the duration and give the focus back to the previous window afterwards."""
    previous = win32gui.GetForegroundWindow()
    if previous != hwnd:
        activate(hwnd)
        time.sleep(0.3)
    try:
        yield
    finally:
        if previous and previous != hwnd and win32gui.IsWindow(previous):
            activate(previous)


def screenshot(hwnd: int | None = None, region: list[int] | None = None) -> bytes:
    """PNG of a window (region [x, y, width, height] relative to it) or of the desktop (region in screen pixels)."""
    def grab(origin):
        if region:
            x, y, w, h = region
            return ImageGrab.grab(bbox=(origin[0] + x, origin[1] + y, origin[0] + x + w, origin[1] + y + h),
                                  all_screens=True)
        return ImageGrab.grab(bbox=tuple(win32gui.GetWindowRect(hwnd)), all_screens=True) if hwnd else \
            ImageGrab.grab(all_screens=True)

    if hwnd:
        with foreground(hwnd):
            image_ = grab(win32gui.GetWindowRect(hwnd)[:2])
    else:
        image_ = grab((0, 0))
    out = io.BytesIO()
    image_.save(out, "PNG")
    return out.getvalue()


def client_image(hwnd: int):
    """PIL image of a window's client area as shown on screen (only meaningful while the window is in front)."""
    left, top = win32gui.ClientToScreen(hwnd, (0, 0))
    _, _, width, height = win32gui.GetClientRect(hwnd)
    return ImageGrab.grab(bbox=(left, top, left + width, top + height), all_screens=True)


def capture(hwnd: int) -> bytes | None:
    """PNG of a window drawn by the window itself (PrintWindow), so it works behind other windows; None when it
    cannot be captured (minimized, or the result is blank)."""
    import win32ui
    from PIL import Image

    if not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd):
        return None
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return None
    window_dc = win32gui.GetWindowDC(hwnd)
    source = win32ui.CreateDCFromHandle(window_dc)
    memory = source.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    try:
        bitmap.CreateCompatibleBitmap(source, width, height)
        memory.SelectObject(bitmap)
        drawn = user32.PrintWindow(hwnd, memory.GetSafeHdc(), 2)  # PW_RENDERFULLCONTENT: DirectX and DWM content too
        image_ = Image.frombuffer("RGB", (width, height), bitmap.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        memory.DeleteDC()
        source.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)
    if not drawn or image_.getextrema() in (((0, 0),) * 3, ((255, 255),) * 3):
        return None
    out = io.BytesIO()
    image_.save(out, "PNG")
    return out.getvalue()


def _key(vk: int, up: bool) -> None:
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP if up else 0, 0)


def _type_char(ch: str) -> None:
    code = win32api.VkKeyScan(ch)
    if code == -1:
        raise ToolError("bad_value", f"cannot type {ch!r} with the current keyboard layout")
    vk, shift = code & 0xFF, bool(code >> 8 & 1)
    if shift:
        _key(0x10, False)
    _key(vk, False)
    _key(vk, True)
    if shift:
        _key(0x10, True)


def send_input(hwnd: int, actions: list[dict]) -> None:
    """Mouse and keyboard input into `hwnd`; points are client-area coordinates. Actions: {"click": [x, y],
    "button"?, "double"?}, {"drag": [[x1, y1], [x2, y2]], "button"?}, {"keys": "ctrl+s"}, {"text": "..."},
    {"wait": seconds}."""
    if not isinstance(actions, list) or not all(isinstance(a, dict) for a in actions):
        raise ToolError("bad_op", "actions must be a list of objects",
                        hint='[{"click": [100, 200]}, {"keys": "ctrl+s"}, {"text": "hello"}, {"wait": 0.5}]')
    with foreground(hwnd):
        for i, action in enumerate(actions):
            button = MOUSE.get(action.get("button", "left"))
            if button is None:
                raise ToolError("bad_value", f"actions[{i}]: button must be left, right or middle")
            if "click" in action:
                x, y = win32gui.ClientToScreen(hwnd, tuple(action["click"]))
                win32api.SetCursorPos((x, y))
                for _ in range(2 if action.get("double") else 1):
                    win32api.mouse_event(button[0], 0, 0, 0, 0)
                    win32api.mouse_event(button[1], 0, 0, 0, 0)
            elif "drag" in action:
                (x1, y1), (x2, y2) = [win32gui.ClientToScreen(hwnd, tuple(p)) for p in action["drag"]]
                win32api.SetCursorPos((x1, y1))
                win32api.mouse_event(button[0], 0, 0, 0, 0)
                for step in range(1, 11):
                    win32api.SetCursorPos((x1 + (x2 - x1) * step // 10, y1 + (y2 - y1) * step // 10))
                    time.sleep(0.02)
                win32api.mouse_event(button[1], 0, 0, 0, 0)
            elif "keys" in action:
                codes = parse_keys(action["keys"])
                for vk in codes:
                    _key(vk, False)
                for vk in reversed(codes):
                    _key(vk, True)
            elif "text" in action:
                for ch in str(action["text"]):
                    _type_char(ch)
            elif "wait" in action:
                time.sleep(min(float(action["wait"]), 30.0))
            else:
                raise ToolError("bad_op", f"actions[{i}]: expected click, drag, keys, text or wait")
            time.sleep(0.05)
