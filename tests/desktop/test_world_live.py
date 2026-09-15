"""Phase 4 live checks: a map changed through the world-content tools opens and saves in the World Editor and runs
in the game with its regions, placed objects and terrain in place (pytest -m editor / -m game)."""
import shutil

import pytest

from corpus import _storage, ladder_maps, open_sample
from wc3mcp.desktop import editor as ed
from wc3mcp.desktop import game
from wc3mcp.formats import unitsdoo, w3c, w3e, w3r
from wc3mcp.mpq.reader import Archive

RESULTS = "wc3mcp\\world_test.txt"


def build_map(target):
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops.elements import elements_edit
    from wc3mcp.ops.placed import placed_edit, placed_list
    from wc3mcp.ops.script import map_validate, script_build, script_validate
    from wc3mcp.ops.terrain import terrain_edit
    from wc3mcp.ops.triggers import triggers_edit
    from wc3mcp.project.workspace import MapProject

    jass = next(p for p in ladder_maps() if open_sample("ladder:" + p.name).read("war3map.j") is not None)
    shutil.copyfile(jass, target)
    catalog = Catalog(_storage(), balance="Custom_V1")
    project = MapProject.open(target)
    elements_edit(project, catalog, "region", [
        {"op": "upsert", "name": "Arena", "left": -256, "bottom": -256, "right": 256, "top": 256}])
    elements_edit(project, catalog, "camera", [{"op": "upsert", "name": "Intro", "x": 0, "y": 0}])
    elements_edit(project, catalog, "sound", [
        {"op": "upsert", "name": "Hello", "path": "Units\\Human\\Footman\\FootmanYesAttack2.flac",
         "label": "FootmanYesAttack", "is_3d": True}])
    created = placed_edit(project, catalog, [
        {"op": "add", "kind": "unit", "type": "hfoo", "x": 64, "y": 64, "owner": 0},
        {"op": "add", "kind": "item", "type": "ratc", "x": -64, "y": -64},
        {"op": "add", "kind": "destructible", "type": "LTbr", "x": 384, "y": 384,
         "drops": {"sets": [[{"item": "YkI1", "chance": 100}]]}},
        {"op": "add", "kind": "unit", "type": "Hpal", "x": -128, "y": 128, "owner": 1, "hero": {"level": 3},
         "abilities": [{"id": "AHhb", "level": 1}, {"id": "AHds", "level": 1}], "inventory": [{"slot": 2, "item": "ratc"}],
         "mana": 50},
        {"op": "add", "kind": "unit", "type": "nogr", "x": 512, "y": -512, "owner": 24, "acquisition": "camp",
         "life": 75, "drops": {"sets": [[{"item": "YYI1", "chance": 50}, {"item": "YiI2", "chance": 30}], []]}},
        {"op": "add", "kind": "unit", "type": "nwgt", "x": -512, "y": -512, "owner": 27, "waygate": "Arena"}])["created"]
    unit, item, barrel = (next(x for x in placed_list(project, catalog, limit=5000)["items"] if x["ref"] == r)
                          for r in created[:3])
    terrain_edit(project, catalog, [{"op": "raise", "x": 0, "y": 0, "radius": 600, "amount": 96},
                                    {"op": "paint", "x": 0, "y": 0, "radius": 300, "tile": "Lgrs"}])
    # a custom text trigger: the editor declares gg_unit_/gg_item_ globals for names used in trigger text, not for
    # names inside GUI "Custom Script" actions
    report = (
        "function Trig_Report_Actions takes nothing returns nothing\n"
        "    call PreloadGenClear()\n"
        "    call PreloadGenStart()\n"
        "    if RectContainsCoords(gg_rct_Arena, 0, 0) and not RectContainsCoords(gg_rct_Arena, 300, 0) then\n"
        '        call Preload("arena-ok")\n'
        "    endif\n"
        f"    call Preload(I2S(GetUnitTypeId({unit['script_name']})))\n"
        f"    call Preload(I2S(GetItemTypeId({item['script_name']})))\n"
        f"    call KillDestructable({barrel['script_name']})\n"
        '    call PreloadGenEnd("wc3mcp\\\\world_test.txt")\n'
        "endfunction\n\n"
        "function InitTrig_Report takes nothing returns nothing\n"
        "    set gg_trg_Report = CreateTrigger(  )\n"
        "    call TriggerAddAction( gg_trg_Report, function Trig_Report_Actions )\n"
        "endfunction\n")
    triggers_edit(project, catalog, [{"op": "trigger", "name": "Report", "script": report, "run_on_init": True}])
    assert script_build(project, catalog)["changed"]
    assert script_validate(project, catalog)["ok"] and map_validate(project, catalog)["errors"] == []
    script = project.read("war3map.j")
    project.save()
    project.close()
    return unit, item, script


@pytest.mark.editor
def test_world_content_opens_and_saves_in_the_editor(tmp_path):
    editor = ed.Editor()
    if editor.status()["running"]:
        pytest.skip("a World Editor is already running")
    target = tmp_path / "World Test.w3x"
    unit, item, script = build_map(target)
    try:
        status = editor.launch(target)
        assert status["map"] == str(target) and status["dialogs"] == []
        saved = editor.save()
        assert saved["saved"] and saved["errors"] == []
    finally:
        editor.quit(discard=True)
    arc = Archive.open(target)
    assert "Arena" in [g.name for g in w3r.parse(arc.read("war3map.w3r")).regions]
    assert "Intro" in [c.name for c in w3c.parse(arc.read("war3map.w3c")).cameras]
    units = unitsdoo.parse(arc.read("war3mapUnits.doo")).units
    assert {(u.id, round(u.x), round(u.y)) for u in units} >= {(b"hfoo", 64, 64), (b"ratc", -64, -64)}
    t = w3e.parse(arc.read("war3map.w3e"))
    assert b"Lgrs" in t.tiles and w3e.ground_height(t, 0, 0) > 90
    edited = arc.read("war3map.j").decode("utf-8")
    assert f"set {unit['script_name']} = BlzCreateUnitWithSkin( p, 'hfoo', 64.0, 64.0, 270.000, 'hfoo' )" in edited
    assert "set gg_rct_Arena = Rect( -256.0, -256.0, 256.0, 256.0 )" in edited and item["script_name"] in edited

    # the editor snaps new destructables, upgrades file versions and rewrites random items with filters, so compare
    # script_build with the editor's own output for the files it saved
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops.script import balance, script_build
    from wc3mcp.project.workspace import MapProject

    project = MapProject.open(target)
    if script_build(project, Catalog(_storage(), balance=balance(project)))["changed"]:
        ours = project.read("war3map.j").decode("utf-8")
        (tmp_path / "editor.j").write_text(edited, "utf-8")
        (tmp_path / "script_build.j").write_text(ours, "utf-8")
        a, b = edited.splitlines(), ours.splitlines()
        first = next(i for i, (x, y) in enumerate(zip(a + [""], b + [""])) if x != y)
        pytest.fail(f"script_build changes the editor's script (both in {tmp_path}); first difference at line "
                    f"{first + 1}:\n{a[first:first + 3]}\n{b[first:first + 3]}")


@pytest.mark.game
def test_world_content_runs_in_the_game(tmp_path):
    target = tmp_path / "World Game Test.w3x"
    build_map(target)
    runner = game.Game()
    result = runner.test(target, results=[RESULTS], timeout=240)
    assert result["missing"] == [], result
    assert result["results"][RESULTS] == ["arena-ok", str(int.from_bytes(b"hfoo", "big")),
                                          str(int.from_bytes(b"ratc", "big"))]
    assert result["closed"]
