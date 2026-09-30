"""The plugin and extension manifests for every harness parse and stay in step with the package version."""
import json
import tomllib
from pathlib import Path

from wc3mcp import __version__

ROOT = Path(__file__).parents[1]


def _json(name: str) -> dict:
    return json.loads((ROOT / name).read_text("utf-8"))


def test_every_manifest_parses_and_carries_the_version():
    assert tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"] == __version__
    for name in ("plugin.json", ".claude-plugin/plugin.json", "gemini-extension.json"):
        assert _json(name)["version"] == __version__, name
    for name in (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json",
                 ".cursor-plugin/marketplace.json"):
        assert _json(name)["plugins"][0]["name"] == "wc3-mcp", name


def test_every_manifest_starts_the_same_server():
    agent = _json("mcp.json")["mcpServers"]["wc3"]
    assert agent["type"] == "stdio" and agent["cwd"] == "${PLUGIN_ROOT}" and agent["env"] == {"PYTHONPATH": "src"}
    for server in (agent, _json("gemini-extension.json")["mcpServers"]["wc3"],
                   _json(".claude-plugin/plugin.json")["mcpServers"]["wc3"]):
        assert server["command"] == "uv" and server["args"][-3:] == ["python", "-m", "wc3mcp.server"]
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["scripts"]
    assert scripts["wc3-mcp"] == "wc3mcp.server:main"
    assert (ROOT / "skills" / "wc3-map-making" / "SKILL.md").is_file()


def test_tool_descriptions_fit_every_client():
    import asyncio

    from wc3mcp import server

    tools = asyncio.run(server.mcp.list_tools())
    assert [t.name for t in tools if len(t.description or "") > 1024] == []   # OpenAI models' limit
