import pytest

from wc3mcp import pathguard
from wc3mcp.errors import ToolError


def test_refuses_paths_inside_install(monkeypatch, tmp_path):
    root = tmp_path / "Warcraft III"
    monkeypatch.setenv("WC3MCP_INSTALL", str(root))
    for p in (root, root / "_retail_" / "x.w3x", root / "sub" / ".." / "Data" / "y"):
        with pytest.raises(ToolError) as e:
            pathguard.ensure_writable(p)
        assert e.value.code == "install_read_only"


def test_install_check_ignores_case(monkeypatch, tmp_path):
    root = tmp_path / "Warcraft III"
    monkeypatch.setenv("WC3MCP_INSTALL", str(root))
    with pytest.raises(ToolError):
        pathguard.ensure_writable(str(root).upper() + "\\Maps\\a.w3x")


def test_allows_paths_outside_install(monkeypatch, tmp_path):
    monkeypatch.setenv("WC3MCP_INSTALL", str(tmp_path / "Warcraft III"))
    assert pathguard.ensure_writable(tmp_path / "Warcraft III2" / "a.w3x").name == "a.w3x"


def test_tool_error_to_dict():
    e = ToolError("bad", "msg", hint="h", op_index=2)
    assert e.to_dict() == {"code": "bad", "message": "msg", "hint": "h", "details": {"op_index": 2}}
