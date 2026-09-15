"""Filesystem locations. Environment overrides keep tests away from real user data."""
import ctypes
import functools
import os
from pathlib import Path


def install_root() -> Path:
    return Path(os.environ.get("WC3MCP_INSTALL", r"D:\Warcraft III"))


@functools.cache
def package_family() -> str | None:
    """The app package this process runs in (the Microsoft Store Python has one), else None."""
    kernel32 = ctypes.windll.kernel32
    length = ctypes.c_uint32(0)
    if kernel32.GetCurrentPackageFamilyName(ctypes.byref(length), None) != 122:   # 15700: not packaged
        return None
    buf = ctypes.create_unicode_buffer(length.value)
    return buf.value if kernel32.GetCurrentPackageFamilyName(ctypes.byref(length), buf) == 0 else None


def home() -> Path:
    if env := os.environ.get("WC3MCP_HOME"):
        return Path(env)
    local = Path(os.environ["LOCALAPPDATA"])
    family = package_family()
    # a packaged Python's writes under AppData\Local land in a private copy that other programs (pjass, JassHelper,
    # the game) cannot see; name that copy's real folder so they find the files
    return (local / "Packages" / family / "LocalCache" / "Local" if family else local) / "wc3mcp"


def documents() -> Path:
    if env := os.environ.get("WC3MCP_DOCUMENTS"):
        return Path(env)
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # CSIDL_PERSONAL (follows OneDrive redirection)
    return Path(buf.value) / "Warcraft III"
