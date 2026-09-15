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

EXPECTED = {"map_new", "map_open", "map_close", "map_save", "map_status", "map_file_read", "map_file_write", "map_snapshot",
            "data_search", "data_get", "data_file", "info_get", "info_edit", "imports_edit",
            "objdata_list", "objdata_get", "objdata_edit", "triggers_tree", "trigger_get", "triggers_edit",
            "script_build", "script_validate", "map_validate", "editor_launch", "editor_status", "editor_map",
            "editor_menu", "editor_screenshot", "editor_dialogs", "editor_dialog_act", "editor_input", "editor_log",
            "game_test", "game_status", "game_close", "elements_list", "elements_edit", "placed_list",
            "placed_edit", "terrain_get", "terrain_edit", "terrain_render"}


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


@needs_install
def test_element_tools(tmp_path):
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    path = str(src)
    payload(call("map_open", {"path": path}))
    created = payload(call("elements_edit", {"path": path, "kind": "region", "ops": [
        {"op": "upsert", "name": "Arena", "left": -256, "bottom": -256, "right": 256, "top": 256, "weather": "RAlr"}]}))
    assert created["created"] == ["Arena"]
    regions = payload(call("elements_list", {"path": path, "kind": "region"}))["items"]
    assert (regions[-1]["script_name"], regions[-1]["weather"]) == ("gg_rct_Arena", "RAlr")
    weather = payload(call("data_search", {"kind": "weather", "query": "RAlr"}))["results"]
    assert "RAlr" in [w["id"] for w in weather]
    err = call("elements_edit", {"path": path, "kind": "region", "ops": [{"op": "delete", "name": "Nope"}]})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "not_found"


@needs_install
def test_placed_tools(tmp_path):
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    path = str(src)
    payload(call("map_open", {"path": path}))
    added = payload(call("placed_edit", {"path": path, "ops": [
        {"op": "add", "kind": "unit", "type": "hfoo", "x": 0, "y": 0, "owner": 1}]}))
    [ref] = added["created"]
    listed = payload(call("placed_list", {"path": path, "kind": "unit", "type_id": "hfoo"}))
    assert ref in [x["ref"] for x in listed["items"]] and listed["bounds"]["playable"]
    err = call("placed_edit", {"path": path, "ops": [{"op": "delete", "ref": "unit:99999"}]})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "not_found"
    if Archive.open(src).read("war3map.j") is not None:
        saved = payload(call("map_save", {"path": path}))
        assert saved["script"]["changed"] and b"CreateUnitsForPlayer1(  )" in Archive.open(src).read("war3map.j")


@needs_install
def test_map_new_tool(tmp_path):
    path = str(tmp_path / "Brand New.w3x")
    status = payload(call("map_new", {"path": path, "width": 32, "height": 32, "players": 2, "name": "Fresh"}))
    assert status["dirty"] == [] and Archive.open(path).read("war3map.j") is not None
    assert payload(call("info_get", {"path": path}))["name"] == "Fresh"
    err = call("map_new", {"path": path})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "exists"


@needs_install
def test_terrain_tools(tmp_path):
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    path = str(src)
    payload(call("map_open", {"path": path}))
    doc = payload(call("terrain_get", {"path": path, "area": [0, 0, 128, 128], "layers": ["height"]}))
    assert len(doc["layers"]["height"]) == 2
    assert payload(call("terrain_edit", {"path": path, "ops": [
        {"op": "raise", "x": 0, "y": 0, "radius": 300, "amount": 50}]}))["changed"]
    image = call("terrain_render", {"path": path, "scale": 1})
    assert not image.isError and image.content[0].type == "image" and image.content[0].mimeType == "image/png"


@needs_install
def test_script_tools_and_save_rebuild(tmp_path):
    maps = [p for p in ladder_maps() if Archive.open(p).read("war3map.j") is not None]
    if not maps:
        pytest.skip("no JASS ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    path = str(src)
    payload(call("map_open", {"path": path}))
    payload(call("triggers_edit", {"path": path, "ops": [{"op": "trigger", "name": "Hello", "actions": [
        {"fn": "DisplayTextToForce", "args": [{"call": "GetPlayersAll"}, "Hi"]}]}]}))
    saved = payload(call("map_save", {"path": path}))
    assert saved["saved"] and saved["script"]["changed"] and saved["validation"]["errors"] == []
    assert b"function InitTrig_Hello takes nothing returns nothing" in Archive.open(src).read("war3map.j")
    assert payload(call("script_validate", {"path": path}))["ok"]
    assert payload(call("map_validate", {"path": path}))["errors"] == []
    assert payload(call("script_build", {"path": path}))["changed"] is False


@needs_install
def test_map_save_rebuilds_the_script_after_element_edits(tmp_path):
    maps = [p for p in ladder_maps() if Archive.open(p).read("war3map.j") is not None]
    if not maps:
        pytest.skip("no JASS ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    path = str(src)
    payload(call("map_open", {"path": path}))
    payload(call("elements_edit", {"path": path, "kind": "region", "ops": [
        {"op": "upsert", "name": "Arena", "left": -256, "bottom": -256, "right": 256, "top": 256}]}))
    saved = payload(call("map_save", {"path": path}))
    assert saved["script"]["changed"] and saved["validation"]["errors"] == []
    assert b"set gg_rct_Arena = Rect( -256.0, -256.0, 256.0, 256.0 )" in Archive.open(src).read("war3map.j")


def test_map_save_takes_turns_with_the_editor(tmp_path, monkeypatch):
    from wc3mcp.desktop import editor

    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    path = str(src)
    payload(call("map_open", {"path": path}))
    payload(call("info_edit", {"path": path, "ops": [{"op": "set", "path": "name", "value": "Turn Test"}]}))
    idle = {"running": True, "map": str(src).upper(), "dirty": True, "untitled": False, "dialogs": []}
    monkeypatch.setattr(editor.EDITOR, "status", lambda: idle)
    err = call("map_save", {"path": path})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "open_in_editor"
    monkeypatch.setattr(editor.EDITOR, "status", lambda: {**idle, "dirty": False})
    saved = payload(call("map_save", {"path": path}))
    assert saved["saved"] and any("editor" in w for w in saved["warnings"])
