"""Phase 5d live check: an AI built only through the tools opens in the AI Editor, and the editor's own export of it
equals ai_export (pytest -m editor)."""
import time

import pytest
import win32gui

from corpus import _storage
from wc3mcp.desktop import editor as ed
from wc3mcp.desktop import win


def _module(editor) -> int:
    return next(h for h in win.windows(editor.pid) if win32gui.GetWindowText(h).startswith("AI Editor"))


def _wait(condition, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        value = condition()
        if value:
            return value
        time.sleep(0.3)
    raise AssertionError("timed out")


def editor_export(editor, source, target) -> None:
    """Open `source` in the AI Editor and export its script to `target` the way a user would."""
    editor.invoke("Module/AI Editor")
    h = _wait(lambda: next((w for w in win.windows(editor.pid) if win32gui.GetWindowText(w).startswith("AI Editor")), None))
    with win.foreground(h):
        win.post_command(h, 64188)   # File/Open AI Data... (only honoured while the module is active)
        _wait(lambda: editor.find_window("Open"))
        editor.dialog_act("Open", [{"control": 1148, "set_text": str(source)}, {"control": 1, "click": True}])
        _wait(lambda: source.name[:20] in win32gui.GetWindowText(_module(editor)))
        assert editor.status()["dialogs"] == []
        win.send_input(_module(editor), [{"keys": "ctrl+e"}])   # File/Export Script...
        _wait(lambda: editor.find_window("Save As"))
        editor.dialog_act("Save As", [{"control": 1001, "set_text": str(target)}, {"control": 1, "click": True}])
        _wait(lambda: target.exists() and not editor.find_window("Save As"))
        time.sleep(1)


@pytest.mark.editor
def test_tool_built_ai_exports_like_the_ai_editor(tmp_path):
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops.ai import ai_edit, ai_export

    editor = ed.Editor()
    if editor.status()["running"]:
        pytest.skip("a World Editor is already running")
    catalog = Catalog(_storage(), balance="Custom_V1")
    source = tmp_path / "Tool Raiders.wai"
    gold = {"fn": "OperatorCompareInteger", "args": [{"call": "GetGold"}, {"preset": "OperatorGreaterEq"}, 400]}
    ai_edit(source, catalog, [
        {"op": "set", "path": "name", "value": "Tool Raiders"},
        {"op": "set", "path": "options.set_player_name", "value": True},
        {"op": "append", "path": "conditions", "value": {"name": "Rich", "condition": gold}},
        {"op": "append", "path": "conditions", "value": {"name": "Late", "condition": {
            "fn": "GetBooleanAnd", "args": [
                {"call": "OperatorCompareInteger", "args": [{"call": "CurrentAttackWave"}, {"preset": "OperatorGreater"}, 2]},
                {"call": "OperatorCompareInteger", "args": [{"call": "GetWood"}, {"preset": "OperatorLess"}, 300]}]}}},
        {"op": "set", "path": "heroes[0]", "value": {"id": "Hamg", "skills": [
            ["AHwe", "AHbz", "AHwe", "AHab", "AHwe", "AHmt", "AHbz", "AHab", "AHbz", "AHab"]] * 3}},
        {"op": "set", "path": "heroes[1]", "value": {"id": "Hpal", "skills": [
            ["AHhb", "AHds", "AHhb", "AHad", "AHhb", "AHre", "AHds", "AHad", "AHds", "AHad"]] * 3}},
        {"op": "set", "path": "hero_orders.order_1_2_3", "value": 70},
        {"op": "set", "path": "hero_orders.order_2_1_3", "value": 30},
        {"op": "append", "path": "build", "value": {"type": "unit", "id": "hbar", "town": "main"}},
        {"op": "append", "path": "build", "value": {"type": "unit", "id": "hero1"}},
        {"op": "append", "path": "build", "value": {"type": "unit", "id": "hfoo", "condition": "Rich"}},
        {"op": "append", "path": "build", "value": {"type": "unit", "id": "hfoo", "condition": "Rich"}},
        {"op": "append", "path": "build", "value": {"type": "upgrade", "id": "Rhme", "condition": {"custom": gold}}},
        {"op": "append", "path": "build", "value": {"type": "expansion", "condition": "Late"}},
        {"op": "append", "path": "harvest", "value": {"resource": "gold", "town": "mine0", "workers": 5}},
        {"op": "append", "path": "harvest", "value": {"resource": "lumber", "workers": "all_not_attacking"}},
        {"op": "set", "path": "groups[0].units", "value": [
            {"id": "hero1", "quantity": 1}, {"id": "hfoo", "quantity": "all", "maximum": 2, "condition": "Late"}]},
        {"op": "append", "path": "groups", "value": {"name": "Rush", "units": [{"id": "hfoo", "quantity": 4, "maximum": 6}]}},
        {"op": "set", "path": "attack.minimum_group", "value": 1},
        {"op": "set", "path": "attack.waves", "value": [{"group": 1, "delay": 0}, {"group": 0, "delay": 45}]},
        {"op": "set", "path": "attack.repeat_waves", "value": 1},
        {"op": "set", "path": "targets[1].condition", "value": "Late"}])
    ours = tmp_path / "ours.ai"
    assert ai_export(source, catalog, dest=str(ours))["validation"]["ok"]
    theirs = tmp_path / "editor.ai"
    editor.launch()
    try:
        editor_export(editor, source, theirs)
    finally:
        editor.quit(discard=True)
    assert theirs.read_bytes() == ours.read_bytes()
