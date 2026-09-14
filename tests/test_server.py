import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from corpus import ladder_maps, needs_install
from wc3mcp import server
from wc3mcp.mpq.reader import Archive
from wc3mcp.mpq.writer import write_archive

EXPECTED = {"map_open", "map_close", "map_save", "map_status", "map_file_read", "map_file_write", "map_snapshot",
            "data_search", "data_get", "data_file", "info_get", "info_edit", "imports_edit",
            "objdata_list", "objdata_get", "objdata_edit", "triggers_tree", "trigger_get", "triggers_edit"}


def call(name: str, args: dict):
    async def run():
        async with create_connected_server_and_client_session(server.mcp._mcp_server) as client:
            return await client.call_tool(name, args)
    return asyncio.run(run())


def payload(result) -> dict:
    assert not result.isError, result.content[0].text
    return json.loads(result.content[0].text)


def test_tools_are_registered():
    assert EXPECTED <= {t.name for t in asyncio.run(server.mcp.list_tools())}


def test_map_tools_end_to_end(tmp_path):
    src = tmp_path / "m.w3x"
    src.write_bytes(write_archive({"war3map.j": b"old"}))
    path = str(src)
    assert payload(call("map_open", {"path": path}))["file_count"] == 1
    payload(call("map_file_write", {"path": path, "name": "war3map.j", "content": "new"}))
    assert payload(call("map_save", {"path": path}))["saved"]
    assert payload(call("map_file_read", {"path": path, "name": "war3map.j"}))["content"] == "new"
    assert Archive.open(src).read("war3map.j") == b"new"
    payload(call("map_close", {"path": path}))
    err = call("map_status", {"path": path})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "not_open"


@needs_install
def test_data_tools():
    hits = payload(call("data_search", {"kind": "unit", "query": "archmage", "balance": None}))["results"]
    assert "Hamg" in [h["id"] for h in hits]
    got = payload(call("data_get", {"kind": "ability", "id": "AHbz", "fields": ["Hbz1"], "balance": None}))
    assert got["fields"]["Hbz1"]["values"] == ["6", "8", "10"]
    common = payload(call("data_file", {"path": "Scripts/common.j", "length": 200}))
    assert common["path"] == "War3.w3mod:Scripts/common.j" and common["truncated"]


def test_tool_calls_are_logged_to_file(tmp_path):
    log_path = server.setup_logging()
    try:
        src = tmp_path / "m.w3x"
        src.write_bytes(write_archive({"a.txt": b"1"}))
        payload(call("map_open", {"path": str(src)}))
        assert call("map_status", {"path": str(tmp_path / "missing.w3x")}).isError
        for handler in server.log.handlers:
            handler.flush()
        text = log_path.read_text("utf-8")
        assert "map_open ok" in text and "map_status error not_open" in text
    finally:
        for handler in list(server.log.handlers):
            server.log.removeHandler(handler)
            handler.close()


def test_stdio_server_starts(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(Path(server.__file__).parents[1]), "WC3MCP_HOME": str(tmp_path / "home")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "wc3mcp.server"], env=env)

    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return {t.name for t in (await session.list_tools()).tools}

    assert EXPECTED <= asyncio.run(run())


def test_info_and_import_tools(tmp_path):
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    path = str(src)
    payload(call("map_open", {"path": path}))
    payload(call("info_edit", {"path": path, "ops": [{"op": "set", "path": "name", "value": "Server Test"}]}))
    assert payload(call("info_get", {"path": path}))["name"] == "Server Test"
    listed = payload(call("imports_edit", {"path": path, "ops": [
        {"op": "add", "path": "war3mapImported/t.txt", "content_base64": "aGk="}]}))
    assert {"path": "war3mapImported/t.txt", "flag": 29, "size": 2} in listed["imports"]
    err = call("info_edit", {"path": path, "ops": [{"op": "set", "path": "players[99].name", "value": "x"}]})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "bad_op"


@needs_install
def test_object_data_tools(tmp_path):
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    path = str(src)
    payload(call("map_open", {"path": path}))
    created = payload(call("objdata_edit", {"path": path, "kind": "unit", "balance": None, "ops": [
        {"op": "create", "base": "hfoo", "set": {"Name": "Tool Guard", "HP": 555}}]}))["created"]
    assert created == ["h000"]
    doc = payload(call("objdata_get", {"path": path, "kind": "unit", "id": "h000", "fields": ["uhpm"],
                                       "balance": None}))
    assert doc["fields"]["uhpm"]["value"] == 555 and doc["name"] == "Tool Guard"
    listed = payload(call("objdata_list", {"path": path, "kind": "unit", "custom_only": True, "balance": None}))
    assert [o["id"] for o in listed["objects"]] == ["h000"]
    err = call("objdata_edit", {"path": path, "kind": "unit", "balance": None,
                                "ops": [{"op": "set", "id": "h000", "set": {"nope": 1}}]})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "unknown_field"


@needs_install
def test_trigger_tools(tmp_path):
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    path = str(src)
    payload(call("map_open", {"path": path}))
    assert payload(call("triggers_tree", {"path": path}))["triggers"][0]["name"] == "Melee Initialization"
    created = payload(call("triggers_edit", {"path": path, "ops": [{"op": "trigger", "name": "Hello", "actions": [
        {"fn": "DisplayTextToForce", "args": [{"call": "GetPlayersAll"}, "Hi"]}]}]}))
    assert created["created"] == ["Hello"]
    doc = payload(call("trigger_get", {"path": path, "name": "Hello"}))
    assert doc["text"].splitlines()[-1] == "    Game - Display to (All players) the text: Hi"
    found = payload(call("data_search", {"kind": "trigger_function", "query": "DisplayTextToForce"}))
    assert "DisplayTextToForce" in [r["id"] for r in found["results"]]
    err = call("triggers_edit", {"path": path, "ops": [{"op": "trigger", "name": "Hello", "actions": [{"fn": "Nope"}]}]})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "unknown_function"
