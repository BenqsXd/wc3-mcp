import subprocess
import time

import pytest

from wc3mcp import config
from wc3mcp.desktop import win
from wc3mcp.errors import ToolError

TREE = [{"label": "File", "id": None, "items": [{"label": "Open Map...", "id": 64188}, {"label": "Save Map", "id": 4}]},
        {"label": "Module", "id": None, "items": [{"label": "Trigger Editor", "id": 1793}]}]


def test_menu_labels():
    assert win.menu_label("&Save Map\tCtrl+S") == "Save Map"
    assert win.menu_label("Se&lect All Special\tCtrl+Shift+~") == "Select All Special"
    assert win.menu_label("") == ""


def test_find_command():
    assert win.find_command(TREE, "file/save map") == 4
    assert win.find_command(TREE, "Module / Trigger Editor") == 1793
    with pytest.raises(ToolError) as e:
        win.find_command(TREE, "File/Nope")
    assert e.value.code == "no_menu_item" and "Save Map" in e.value.details["choices"]
    with pytest.raises(ToolError):
        win.find_command(TREE, "File")  # a submenu, not a command


def test_parse_keys():
    assert win.parse_keys("ctrl+shift+s") == [0x11, 0x10, ord("S")]
    assert win.parse_keys("F4") == [0x73]
    assert win.parse_keys("enter") == [0x0D]
    with pytest.raises(ToolError):
        win.parse_keys("hyper+x")


@pytest.mark.editor
def test_editor_main_window_menus_and_screenshot():
    if win.processes("World Editor.exe"):
        pytest.skip("a World Editor is already running")
    exe = config.install_root() / "_retail_" / "x86_64" / "World Editor.exe"
    process = subprocess.Popen([str(exe), "-launch"], cwd=exe.parent)
    main = None
    try:
        for _ in range(240):
            main = next((h for h in win.windows(process.pid) if win.info(h)["class"] == "OsWindow" and win.window_menu(h)),
                        None)
            if main:
                break
            time.sleep(0.5)
        assert main, "the editor window did not appear"
        tree = win.window_menu(main)
        assert win.find_command(tree, "File/Save Map") == 4
        assert win.find_command(tree, "Module/Trigger Editor") == 1793
        assert win.screenshot(main)[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        if main:
            win.close(main)
        try:
            process.wait(30)
        except subprocess.TimeoutExpired:
            process.kill()
