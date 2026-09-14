"""Locate local Warcraft III data for corpus tests (read at runtime, never committed)."""
import functools
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


CASC_SAMPLE_MAPS = (
    "Campaign/Reforged/ROC/Human01.w3x",            # w3i v39, many imports, locale strings
    "Campaign/Classic/ROC/Undead02Interlude.w3m",   # w3i v39
    "Campaign/Classic/TFT/HumanX01.w3x",            # w3i v39 players with flag 0x40
    "Campaign/Reforged/ROC/Prologue01.w3x",         # w3i v39
    "Maps/Scenario/(4)WarChasers.w3m",              # w3i v33, JASS
    "Maps/FrozenThrone/Community/2023Season2/(8)RoyalGardens_S2_v1.2.w3x",  # w3i v33, Lua
    "Maps/FrozenThrone/(10)RagingStream.w3x",       # w3i v31
    "Campaign/Classic/TFT/HumanX04Interlude.w3x",   # w3i v31, object data v2
    "Campaign/Reforged/ROC/Human05.w3x",            # wtg with deleted-id counters (comments, kind 128)
)


@functools.cache
def _storage():
    from wc3mcp.casc.storage import open_storage

    return open_storage(INSTALL)


@functools.cache
def _ladder_by_name() -> dict:
    return {p.name: p for p in ladder_maps()}


def sample_map_ids() -> list[str]:
    ids = [f"ladder:{name}" for name in _ladder_by_name()]
    if HAVE_INSTALL:
        ids += [f"casc:{m}" for m in CASC_SAMPLE_MAPS]
    return ids


@functools.cache
def open_sample(map_id: str):
    from wc3mcp.mpq.reader import Archive

    kind, name = map_id.split(":", 1)
    if kind == "casc":
        return Archive(_storage().read("War3.w3mod:" + name))
    return Archive.open(_ladder_by_name()[name])
