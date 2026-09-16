import shutil

import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps, open_sample
from wc3mcp.ops import probe
from wc3mcp.ops.triggers import triggers_tree
from wc3mcp.project.workspace import MapProject


def test_script_reports_through_preload():
    jass = probe.script("jass", 10)
    assert "function InitTrig_wc3mcpProbe takes nothing returns nothing" in jass
    assert r'call PreloadGenEnd("wc3mcp\\probe.txt")' in jass and "TriggerRegisterTimerEvent" in jass
    lua = probe.script("lua", 5)
    assert "function InitTrig_wc3mcpProbe()" in lua and r'PreloadGenEnd("wc3mcp\\probe.txt")' in lua


def test_parse_report():
    assert probe.parse(["probe=ok", "seconds=10.00", "player0.units=12", "player0.gold=500"]) == {
        "probe": "ok", "seconds": "10.00", "player0.units": 12, "player0.gold": 500}


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
def test_build_makes_a_copy_that_reports(tmp_path):
    from wc3mcp.gamedata.catalog import Catalog

    maps = [p for p in ladder_maps() if open_sample("ladder:" + p.name).read("war3map.wtg") is not None]
    if not maps:
        pytest.skip("no ladder map with triggers")
    source = tmp_path / maps[0].name
    shutil.copyfile(maps[0], source)
    copy = probe.build(source, tmp_path / "probe" / maps[0].name, Catalog(_storage(), balance="Custom_V1"))
    assert copy.is_file() and source.read_bytes() != copy.read_bytes()
    project = MapProject.open(copy)
    try:
        assert probe.NAME in [t["name"] for t in triggers_tree(project, Catalog(_storage()))["triggers"]]
        assert "PreloadGenEnd" in project.read("war3map.j").decode("utf-8", "replace")
        assert any(f["name"].lower() == "war3mapmap.blp" for f in project.list_files())
    finally:
        project.close(discard=True)
