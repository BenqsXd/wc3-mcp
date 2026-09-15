"""Phase 5c live check: a campaign built only through the tools opens in the Campaign Editor and saves without a
warning, and the editor keeps everything the tools wrote (pytest -m editor)."""
import pytest

from corpus import _storage
from wc3mcp.desktop import editor as ed


@pytest.mark.editor
def test_tool_built_campaign_opens_and_saves_in_the_campaign_editor(tmp_path):
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops.campaign import campaign_edit, campaign_get, new_campaign
    from wc3mcp.ops.newmap import new_map
    from wc3mcp.ops.objdata import objdata_edit
    from wc3mcp.project.workspace import MapProject

    editor = ed.Editor()
    if editor.status()["running"]:
        pytest.skip("a World Editor is already running")
    catalog = Catalog(_storage(), balance="Custom_V1")
    maps = []
    for name in ("Arrival", "Finale"):
        maps.append(tmp_path / f"{name}.w3x")
        new_map(maps[-1], catalog, width=32, height=32, players=1, name=name).close()
    target = tmp_path / "Saga.w3n"
    project = new_campaign(target, catalog, name="Saga", author="Tools")
    assert campaign_edit(project, catalog, [
        {"op": "add_map", "source": str(maps[0])}, {"op": "add_map", "source": str(maps[1])},
        {"op": "set", "path": "description", "value": "Built by wc3mcp"},
        {"op": "set", "path": "variable_difficulty", "value": True},
        {"op": "set", "path": "minimap", "value": {"map": "Finale.w3x"}},
        {"op": "set", "path": "loading_screen.background", "value": {"preset": "Loading - Human 01"}},
        {"op": "set", "path": "loading_screen.ambient_sound", "value": {"preset": "Orc"}},
        {"op": "set", "path": "loading_screen.cursor", "value": "night_elf"},
        {"op": "set", "path": "loading_screen.fog", "value": {"style": "linear", "z_start": 1000, "z_end": 4000,
                                                               "density": 0.5, "color": {"r": 40, "g": 60, "b": 80}}},
        {"op": "append", "path": "buttons", "value": {"chapter": "Chapter One", "title": "Arrival",
                                                      "map": "Arrival.w3x", "visible": True}},
        {"op": "append", "path": "buttons", "value": {"chapter": "Finale", "title": "The End", "map": "Finale.w3x",
                                                      "cinematic": True}}])["warnings"] == []
    objdata_edit(project, catalog, "unit", [{"op": "set", "id": "hfoo", "set": {"uhpm": 777}}])
    before = campaign_get(project, catalog)
    project.save()
    project.close()
    try:
        status = editor.launch(target)
        assert status["campaign"].endswith("/Saga.w3n") and status["dialogs"] == []
        saved = editor.save_campaign()
        assert saved["saved"] and saved["warnings"] == []
    finally:
        editor.quit(discard=True)
    reopened = MapProject.open(target)
    after = campaign_get(reopened, catalog)
    assert after.pop("campaign_version") == before.pop("campaign_version") + 1
    assert after == before
