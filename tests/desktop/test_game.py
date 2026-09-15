import shutil

import pytest

from corpus import _storage, ladder_maps, open_sample
from wc3mcp.desktop import game

PRELOAD = ('function PreloadFiles takes nothing returns nothing\n\n\tcall PreloadStart()\n'
           '\tcall Preload( "wc3mcp-probe-ok" )\n\tcall Preload( "second line" )\n\tcall PreloadEnd( 0.0 )\n\nendfunction\n')


def test_parse_preload():
    assert game.parse_preload(PRELOAD) == ["wc3mcp-probe-ok", "second line"]
    assert game.parse_preload("") == []


def test_interesting_log_lines():
    lines = ["9/15 08:52:52.967  GameMain Started",
             "9/15 08:52:55.802  Opening map - C:/Maps/x.w3x",
             "9/15 08:52:55.802  Opening mod - C:/Maps/x.w3x",
             "9/15 08:52:54.306  prism: Info: vendorId: NVIDIA",
             "9/15 08:53:03.032  [CLoginCallbacks] LoginDoorClose called"]
    assert game.interesting(lines) == [lines[0], lines[4]]


@pytest.mark.game
def test_game_run_returns_preload_results(tmp_path):
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops.script import script_build
    from wc3mcp.ops.triggers import triggers_edit
    from wc3mcp.project.workspace import MapProject

    jass = next(p for p in ladder_maps() if open_sample("ladder:" + p.name).read("war3map.j") is not None)
    target = tmp_path / "Game Test.w3x"
    shutil.copyfile(jass, target)
    catalog = Catalog(_storage())
    project = MapProject.open(target)
    lines = ["call PreloadGenClear()", "call PreloadGenStart()", 'call Preload("wc3mcp-game-test")',
             'call PreloadGenEnd("wc3mcp\\\\game_test.txt")']
    triggers_edit(project, catalog, [{"op": "trigger", "name": "Report", "events": [{"fn": "MapInitializationEvent"}],
                                      "actions": [{"fn": "CustomScriptCode", "args": [line]} for line in lines]}])
    script_build(project, catalog)
    project.save()
    project.close()

    runner = game.Game()
    result = runner.test(target, results=["wc3mcp\\game_test.txt"], timeout=240)
    assert result["results"] == {"wc3mcp\\game_test.txt": ["wc3mcp-game-test"]} and result["missing"] == []
    assert result["closed"] and runner.status()["running"] is False
    assert any("GameMain Started" in line for line in result["log"])
