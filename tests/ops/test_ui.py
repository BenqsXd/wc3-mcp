import pytest

from corpus import HAVE_INSTALL, _storage
from wc3mcp.errors import ToolError
from wc3mcp.formats import fdf
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.newmap import new_map
from wc3mcp.ops.ui import ui_edit, ui_get

SAMPLE = """// a panel
IncludeFile "UI\\FrameDef\\UI\\EscMenuTemplates.fdf",

Frame "BACKDROP" "MyPanel" INHERITS "EscMenuBackdropTemplate" {
    Width 0.2,
    Height 0.12,
    SetPoint TOPLEFT, "ConsoleUI", TOPLEFT, 0.01, -0.01,

    Frame "TEXT" "MyPanelTitle" {
        SetPoint TOP, "MyPanel", TOP, 0.0, -0.008,
        Text "SCORE",
        FontJustificationH JUSTIFYCENTER,
    }
}
"""


def test_parse_keeps_statements_and_round_trips():
    tree = fdf.parse(SAMPLE)
    assert fdf.includes(tree) == ["UI\\FrameDef\\UI\\EscMenuTemplates.fdf"]
    names = [(t, n, parent) for t, n, _node, parent in fdf.frames(tree)]
    assert names == [("BACKDROP", "MyPanel", None), ("TEXT", "MyPanelTitle", "MyPanel")]
    panel = next(node for t, n, node, _p in fdf.frames(tree) if n == "MyPanel")
    assert {"key": "Width", "args": [0.2]} in panel["statements"]
    assert {"key": "SetPoint", "args": ["TOPLEFT", "ConsoleUI", "TOPLEFT", 0.01, -0.01]} in panel["statements"]
    text = fdf.serialize(tree)
    assert 'Frame "BACKDROP" "MyPanel" INHERITS "EscMenuBackdropTemplate" {' in text
    assert "SetPoint TOPLEFT \"ConsoleUI\" TOPLEFT 0.01 -0.01," in text
    assert fdf.parse(text) == tree                      # the values survive, decimals included


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
def test_every_shipped_layout_file_round_trips():
    catalog = Catalog(_storage(), balance=None, hd=False)
    checked = 0
    for path in catalog.storage.list("*.fdf"):
        data = catalog.storage.read(path)
        if data is None:
            continue
        tree = fdf.parse(data)
        assert fdf.parse(fdf.serialize(tree)) == tree, path
        checked += 1
    assert checked > 50


@pytest.fixture
def game_map(tmp_path):
    catalog = Catalog(_storage(), balance="Custom_V1")
    return new_map(str(tmp_path / "Ui.w3x"), catalog, width=32, height=32, tileset="L", players=1), catalog


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
def test_ui_edit_imports_the_layout_with_a_toc_and_a_loader(game_map):
    project, catalog = game_map
    assert ui_get(project, catalog)["files"] == []
    result = ui_edit(project, catalog, "score.fdf", text=SAMPLE)
    assert result["path"] == "war3mapImported\\score.fdf" and result["toc"] == "war3mapImported\\score.toc"
    assert result["frames"] == ["MyPanel", "MyPanelTitle"] and result["problems"] == []
    assert 'BlzLoadTOCFile("war3mapImported\\\\score.toc")' in result["script"]
    listed = ui_get(project, catalog)["files"]
    assert listed == ["war3mapImported\\score.fdf", "war3mapImported\\score.toc"]
    doc = ui_get(project, catalog, "war3mapImported\\score.fdf")
    assert doc["source"] == "map" and [f["name"] for f in doc["frames"]] == ["MyPanel", "MyPanelTitle"]
    assert doc["frames"][0]["inherits"] == "EscMenuBackdropTemplate"
    toc = ui_get(project, catalog, "war3mapImported\\score.toc")
    assert toc["kind"] == "toc" and toc["files"] == ["score.fdf"]


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
def test_ui_check_names_the_mistakes_that_cost_a_launch(game_map):
    project, catalog = game_map
    broken = """
Frame "PANEL" "Broken" {
    SetPoint MIDDLE, "Nowhere", TOPLEFT, 0.0, 0.0,
    BackdropBackground "war3mapImported\\\\missing.blp",
}
"""
    problems = ui_edit(project, catalog, "broken.fdf", text=broken)["problems"]
    kinds = " | ".join(p["problem"] for p in problems)
    assert "'PANEL' is not one the game knows" in kinds
    assert "'MIDDLE' is not an anchor point" in kinds
    assert "SetPoint refers to 'Nowhere'" in kinds
    assert "missing.blp" in kinds and "imports" in kinds
    good = ui_edit(project, catalog, "good.fdf", statements=[
        {"block": "Frame", "args": ["BACKDROP", "Ok"], "statements": [
            {"key": "Width", "args": [0.1]},
            {"key": "SetPoint", "args": ["TOPLEFT", "ConsoleUI", "TOPLEFT", 0.0, 0.0]},
            {"key": "BackdropBackground", "args": ["ReplaceableTextures\\CommandButtons\\BTNFootman.blp"]}]}])
    assert good["problems"] == [] and good["frames"] == ["Ok"]


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
def test_ui_edit_refuses_what_it_cannot_write(game_map):
    project, catalog = game_map
    for kwargs, code in (({"path": "panel.txt", "text": SAMPLE}, "bad_value"),
                         ({"path": "panel.fdf"}, "bad_value"),
                         ({"path": "panel.fdf", "text": SAMPLE, "statements": []}, "bad_value"),
                         ({"path": "panel.fdf", "text": "Frame {"}, "bad_value")):
        with pytest.raises(ToolError) as e:
            ui_edit(project, catalog, **kwargs)
        assert e.value.code == code, kwargs
    with pytest.raises(ToolError) as e:
        ui_get(project, catalog, "war3mapImported\\nothing.fdf")
    assert e.value.code == "not_found"
