"""Locate local Warcraft III data for corpus tests (read at runtime, never committed)."""
import os
from pathlib import Path

import pytest

INSTALL = Path(os.environ.get("WC3MCP_INSTALL", r"D:\Warcraft III"))
HAVE_INSTALL = (INSTALL / ".build.info").is_file()
needs_install = pytest.mark.skipif(not HAVE_INSTALL, reason="Warcraft III install not found")


def ladder_maps() -> list[Path]:
    from wc3mcp import config

    root = config.documents() / "Maps" / "Download"
    seen, out = set(), []
    for p in sorted(root.rglob("*.w3x")) if root.is_dir() else []:
        if p.name.lower() not in seen:
            seen.add(p.name.lower())
            out.append(p)
    return out
