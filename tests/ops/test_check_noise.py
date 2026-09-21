"""The checks must stay quiet on maps that work. A new rule that shouts about every map is worse than no rule, so
every check runs over the shipped sample maps and, when they are there, the maps in the folder below, and
it has to report no errors and only the warnings a real map is allowed to carry.
"""
import os
from pathlib import Path

import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps, open_sample, sample_map_ids
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.script import map_validate
from wc3mcp.project.workspace import MapProject
from wc3mcp.script.lint import lint

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")

# warnings a finished map is allowed to carry: they are facts about the map, not defects of the checks
EXPECTED = {"derived_files", "model", "start_location", "import", "script_language", "locked_ability",
            "command_card", "inherited_builds", "reachable", "order_string", "ability_order"}


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance="Custom_V1")


def _own_maps() -> list[Path]:
    folder = Path(os.environ.get("WC3MCP_TEST_MAPS", r"D:\war3"))
    return sorted(folder.glob("*.w3x")) if folder.is_dir() else []


@pytest.mark.parametrize("map_path", _own_maps(), ids=lambda p: p.name)
def test_the_checks_stay_quiet_on_a_working_map(map_path, catalog):
    project = MapProject.open(map_path)
    try:
        result = map_validate(project, catalog)
        assert result["errors"] == [], [e["message"][:120] for e in result["errors"][:3]]
        unexpected = [w for w in result["warnings"] if w["check"] not in EXPECTED]
        assert unexpected == [], [w["message"][:120] for w in unexpected[:3]]
        assert len(result["warnings"]) <= 6, [w["check"] for w in result["warnings"]]
        for name in ("war3map.j", r"scripts\war3map.j"):
            try:
                text = project.read(name).decode("utf-8", "replace")
            except Exception:   # noqa: BLE001 - a Lua map or a map without that file
                continue
            hits = lint(text)
            # 6, not 4: MapA carries library triggers whose InitTrig the pre-1.3 wrapper gave an action
            # (dead_trigger); the 1.3 wrapper writes an empty InitTrig for a library, so new maps do not.
            assert len(hits) <= 6, [f"{h['rule']} line {h['line']}" for h in hits[:5]]
            break
    finally:
        project.close(discard=True)


@pytest.mark.parametrize("map_id", [m for m in sample_map_ids() if m.startswith("casc:")][:4])
def test_the_checks_report_no_errors_on_a_shipped_map(map_id, catalog, tmp_path):
    arc = open_sample(map_id)
    src = tmp_path / (map_id.rsplit("/", 1)[-1] or "map.w3x")
    src.write_bytes(arc.data)
    project = MapProject.open(src)
    try:
        assert map_validate(project, catalog)["errors"] == []
    finally:
        project.close(discard=True)


def test_the_lint_is_quiet_on_a_ladder_map(catalog, tmp_path):
    if not ladder_maps():
        pytest.skip("no ladder maps in Documents")
    src = tmp_path / ladder_maps()[0].name
    src.write_bytes(ladder_maps()[0].read_bytes())
    project = MapProject.open(src)
    try:
        text = project.read("war3map.j").decode("utf-8", "replace")
        assert lint(text) == []
    finally:
        project.close(discard=True)
