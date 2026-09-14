"""Filesystem locations. Environment overrides keep tests away from real user data."""
import ctypes
import os
from pathlib import Path


def install_root() -> Path:
    return Path(os.environ.get("WC3MCP_INSTALL", r"D:\Warcraft III"))


def home() -> Path:
    return Path(os.environ.get("WC3MCP_HOME") or Path(os.environ["LOCALAPPDATA"]) / "wc3mcp")


def documents() -> Path:
    if env := os.environ.get("WC3MCP_DOCUMENTS"):
        return Path(env)
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # CSIDL_PERSONAL (follows OneDrive redirection)
    return Path(buf.value) / "Warcraft III"
