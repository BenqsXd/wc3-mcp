"""Phase 5e live check: an icon converted by the asset tools and a model edited by them, imported into a map and used
by a custom unit, load in the World Editor without errors (pytest -m editor)."""
import shutil

import pytest

from corpus import _storage, ladder_maps, open_sample
from wc3mcp.desktop import editor as ed
from wc3mcp.mpq.reader import Archive

ICON = "war3mapImported\\BTNToolFootman.blp"
MODEL = "war3mapImported\\ToolFootman.mdx"
MISSING = "war3mapImported\\NoSuchModel.mdx"   # control: shows the editor reports models it cannot load


def build_map(target) -> str:
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops import assets
    from wc3mcp.ops.objdata import objdata_edit
    from wc3mcp.ops.placed import placed_edit
    from wc3mcp.ops.script import map_validate, script_build
    from wc3mcp.project.workspace import MapProject

    jass = next(p for p in ladder_maps() if open_sample("ladder:" + p.name).read("war3map.j") is not None)
    shutil.copyfile(jass, target)
    catalog = Catalog(_storage(), balance="Custom_V1")
    project = MapProject.open(target)
    project_for = {str(target): project}.__getitem__
    assets.asset_edit({"game": "ReplaceableTextures/CommandButtons/BTNFootman.dds"}, {"map": str(target), "name": ICON},
                      [{"op": "tint", "color": [40, 220, 90], "strength": 0.5}, {"op": "icon", "kind": "BTN"}],
                      project_for, catalog.storage)
    assets.asset_edit({"game": "Units/Human/Footman/Footman.mdx"}, {"map": str(target), "name": MODEL},
                      [{"op": "scale", "factor": 1.6}, {"op": "rename_sequence", "sequence": "Stand - 1", "name": "Stand"},
                       {"op": "add_attachment", "name": "Sprite First Ref", "parent": 0, "position": [0, 0, 150]}],
                      project_for, catalog.storage)
    unit, control = objdata_edit(project, catalog, "unit", [
        {"op": "create", "base": "hfoo", "set": {"Name": "Tool Footman", "uico": ICON, "umdl": MODEL}},
        {"op": "create", "base": "hfoo", "set": {"Name": "Missing Model", "umdl": MISSING}}])["created"]
    placed_edit(project, catalog, [{"op": "add", "kind": "unit", "type": unit, "x": 0, "y": 0, "owner": 0},
                                   {"op": "add", "kind": "unit", "type": control, "x": 128, "y": 0, "owner": 0}])
    script_build(project, catalog)
    assert map_validate(project, catalog)["errors"] == []
    project.save()
    project.close()
    return unit


@pytest.mark.editor
def test_imported_icon_and_model_load_in_the_editor(tmp_path):
    editor = ed.Editor()
    if editor.status()["running"]:
        pytest.skip("a World Editor is already running")
    target = tmp_path / "Asset Test.w3x"
    build_map(target)
    try:
        status = editor.launch(target)
        assert status["map"] == str(target) and status["dialogs"] == []
        (tmp_path / "editor.png").write_bytes(editor.screenshot("main"))
        saved = editor.save()
        assert saved["saved"] and saved["errors"] == []
    finally:
        editor.quit(discard=True)
    # the editor starts a new log at each launch; it creates every placed unit's model while it loads the map and
    # logs "model creation failed - <path>" or "Could not load file: <path>" for the ones it cannot read
    failures = [line for line in editor.log(100000)["log"]
                if "war3mapimported" in line.lower() and ("failed" in line or "Could not load" in line)]
    assert failures and all("NoSuchModel" in line for line in failures), failures
    arc = Archive.open(target)
    assert arc.read(ICON)[:4] == b"BLP1" and arc.read(MODEL)[:4] == b"MDLX"
