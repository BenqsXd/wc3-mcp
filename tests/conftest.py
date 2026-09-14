import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WC3MCP_HOME", str(tmp_path / "wc3mcp-home"))
