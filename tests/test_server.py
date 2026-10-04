import asyncio
import json
import os
import sys
import time
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
            "game_test", "game_regress", "game_status", "game_close", "elements_list", "elements_edit", "placed_list",
            "placed_edit", "terrain_get", "terrain_edit", "terrain_render", "campaign_new", "campaign_get",
            "campaign_edit", "ai_get", "ai_edit", "ai_export", "asset_info", "asset_convert", "asset_edit",
            "asset_preview", "constants_get", "constants_edit", "image_crop", "replay_read", "desync_read"}


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
    assert payload(call("map_save", {"path": path, "validate": False}))["saved"]   # "new" is no valid JASS
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
    assert got["fields"]["Hbz1"] == ["6", "8", "10"]          # compact by default: raw code -> values
    wide = payload(call("data_get", {"kind": "ability", "id": "AHbz", "fields": ["Hbz1"], "balance": None,
                                     "verbose": True}))
    assert wide["fields"]["Hbz1"]["values"] == ["6", "8", "10"] and wide["fields"]["Hbz1"]["field"] == "Data"
    both = payload(call("data_get", {"kind": "ability", "id": ["AHbz", "AHtb"], "fields": ["aord"], "balance": None}))
    assert [o["id"] for o in both["objects"]] == ["AHbz", "AHtb"]
    assert both["objects"][1]["fields"] == {"aord": "thunderbolt"} and "orders" not in both["objects"][1]
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
def test_campaign_tools(tmp_path):
    chapter = str(tmp_path / "Ch1.w3x")
    payload(call("map_new", {"path": chapter, "width": 32, "height": 32, "players": 1}))
    payload(call("map_close", {"path": chapter}))
    path = str(tmp_path / "Saga.w3n")
    payload(call("campaign_new", {"path": path, "name": "Saga"}))
    payload(call("campaign_edit", {"path": path, "ops": [
        {"op": "add_map", "source": chapter},
        {"op": "append", "path": "buttons", "value": {"chapter": "One", "title": "Start", "map": "Ch1.w3x"}}]}))
    saved = payload(call("map_save", {"path": path}))
    assert saved["saved"] and "script" not in saved and saved["validation"]["errors"] == []
    assert payload(call("campaign_get", {"path": path}))["buttons"][0]["title"] == "Start"
    err = call("campaign_get", {"path": chapter})
    assert err.isError and "not_open" in err.content[0].text


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
    assert doc["fields"]["uhpm"] == 555 and doc["modified"] == ["uhpm"] and doc["name"] == "Tool Guard"
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
    ops = tmp_path / "regions.json"
    ops.write_text(json.dumps([{"op": "upsert", "name": f"R{i}", "left": -64 * i, "bottom": 0, "right": 64,
                                "top": 64 * (i + 1)} for i in range(3)]))
    payload(call("elements_edit", {"path": path, "kind": "region", "ops_file": str(ops)}))
    assert [r["name"] for r in payload(call("elements_list", {"path": path, "kind": "region"}))["items"]] == \
        ["R0", "R1", "R2"]
    shown = call("terrain_render", {"path": path, "scale": 2, "area": [-512, -512, 512, 512]})
    assert shown.content[0].type == "image" and json.loads(shown.content[1].text)["tiles"] == [8, 8]
    flow = payload(call("map_flow", {"path": path, "origins": ["start:0"], "targets": ["R1", [0, 0]]}))
    assert [t["target"] for t in flow["targets"]] == ["R1", "(0, 0)"] and flow["cell_units"] == 32


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


@needs_install
def test_map_save_keeps_the_minimap_in_step_with_the_terrain(tmp_path):
    from wc3mcp.formats import blp

    import base64

    from PIL import Image

    path = str(tmp_path / "Minimap.w3x")
    payload(call("map_new", {"path": path, "width": 32, "height": 32}))
    center = lambda: blp.decode(Archive.open(path).read("war3mapMap.blp")).getpixel((128, 128))  # noqa: E731
    flat = center()
    payload(call("terrain_edit", {"path": path, "ops": [{"op": "paint", "x": 0, "y": 0, "radius": 512, "tile": "Lgrs"}]}))
    assert payload(call("map_save", {"path": path}))["minimap"] == "rebuilt" and center() != flat

    # a map without one gets one (the game quits right after login on such a map)
    payload(call("map_file_write", {"path": path, "name": "war3mapMap.blp", "delete": True}))
    assert payload(call("map_save", {"path": path}))["minimap"] == "added"

    # an imported war3mapMap.blp is the map maker's own and stays
    own = blp.encode(Image.new("RGB", (256, 256), (200, 0, 200)), mipmaps=False)
    payload(call("imports_edit", {"path": path, "ops": [
        {"op": "add", "path": "war3mapMap.blp", "content_base64": base64.b64encode(own).decode()}]}))
    payload(call("terrain_edit", {"path": path, "ops": [{"op": "paint", "x": 0, "y": 0, "radius": 512, "tile": "Ldrt"}]}))
    assert "minimap" not in payload(call("map_save", {"path": path}))
    assert Archive.open(path).read("war3mapMap.blp") == own


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


def test_map_save_names_the_editor_when_it_holds_the_file(tmp_path, monkeypatch):
    from wc3mcp.project import workspace

    src = tmp_path / "held.w3x"
    src.write_bytes(write_archive({"war3map.j": b"old"}))
    path = str(src)
    payload(call("map_open", {"path": path}))
    payload(call("map_file_write", {"path": path, "name": "war3map.j", "content": "new"}))
    monkeypatch.setattr(workspace.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError(5, "Access is denied")))
    monkeypatch.setattr(server.desktop_editor.EDITOR, "status", lambda: {
        "running": True, "map": path, "dirty": False, "campaign": None, "campaign_dirty": False})
    err = call("map_save", {"path": path, "validate": False})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "editor_holds_map"
    monkeypatch.undo()
    payload(call("map_close", {"path": path, "discard": True}))


def test_tools_resume_a_working_copy_after_a_restart(tmp_path):
    src = tmp_path / "resumed.w3x"
    src.write_bytes(write_archive({"war3map.j": b"old"}))
    path = str(src)
    payload(call("map_open", {"path": path}))
    payload(call("map_file_write", {"path": path, "name": "war3map.j", "content": "edited"}))
    server._projects.clear()   # as if the server process had restarted
    assert payload(call("map_file_read", {"path": path, "name": "war3map.j"}))["content"] == "edited"
    assert payload(call("map_status", {"path": path}))["dirty"] == ["war3map.j"]
    payload(call("map_close", {"path": path, "discard": True}))
    err = call("map_status", {"path": path})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "not_open"


@needs_install
def test_map_new_reports_its_fill_tile(tmp_path):
    plain = str(tmp_path / "plain.w3x")
    assert payload(call("map_new", {"path": plain, "width": 32, "height": 32}))["fill_tile"] == "Ldrt"
    grass = str(tmp_path / "grass.w3x")
    result = payload(call("map_new", {"path": grass, "width": 32, "height": 32, "fill_tile": "Lgrs"}))
    assert result["fill_tile"] == "Lgrs"
    assert payload(call("terrain_get", {"path": grass}))["layers"]["texture"][0][0] == "Lgrs"
    err = call("map_new", {"path": str(tmp_path / "bad.w3x"), "fill_tile": "Vgrs"})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "bad_value"
    for path in (plain, grass):
        payload(call("map_close", {"path": path, "discard": True}))


@needs_install
def test_data_search_scopes_tiles_to_a_tileset():
    result = payload(call("data_search", {"kind": "tile", "query": "", "tileset": "Lordaeron Summer", "limit": 100}))
    assert result["results"] and all(r["tileset"] == "L" for r in result["results"])
    assert {r["id"] for r in result["results"]} >= {"Lgrs", "Ldrt"}
    err = call("data_search", {"kind": "unit", "tileset": "L"})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "bad_value"


def test_bulk_ops_come_from_a_file(tmp_path):
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    path = str(src)
    payload(call("map_open", {"path": path}))
    ops = tmp_path / "trees.json"
    ops.write_text(json.dumps([{"op": "add", "kind": "destructible", "columns": ["type", "x", "y"],
                                "rows": [["LTlt", x, 256] for x in range(-512, 512, 128)]}]), "utf-8")
    added = payload(call("placed_edit", {"path": path, "ops_file": str(ops)}))
    assert added["created_count"] == 8 and len(added["created"]) == 1 and ".." in added["created"][0]
    script = tmp_path / "hello.j"
    script.write_text('call BJDebugMsg("hello")\n', "utf-8")
    trig = tmp_path / "triggers.json"
    trig.write_text(json.dumps({"ops": [{"op": "trigger", "name": "Hello", "script_file": str(script)}]}), "utf-8")
    if Archive.open(src).read("war3map.wtg") is not None:
        edited = payload(call("triggers_edit", {"path": path, "ops_file": str(trig)}))
        assert edited["changed"] and "Hello" in payload(call("trigger_get", {"path": path, "name": "Hello"}))["script"]
    for args in ({"path": path}, {"path": path, "ops": [], "ops_file": str(ops)},
                 {"path": path, "ops_file": str(tmp_path / "missing.json")}):
        err = call("terrain_edit", args)
        assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "bad_value"
    payload(call("map_close", {"path": path, "discard": True}))


def test_map_save_merges_an_editor_save(tmp_path):
    src = tmp_path / "merged.w3x"
    src.write_bytes(write_archive({"war3map.j": b"old", "war3map.wpm": b"old path"}))
    path = str(src)
    payload(call("map_open", {"path": path}))
    payload(call("map_file_write", {"path": path, "name": "war3map.j", "content": "mine"}))
    src.write_bytes(write_archive({"war3map.j": b"old", "war3map.wpm": b"editor path"}))
    err = call("map_save", {"path": path, "validate": False, "rebuild_script": "never"})
    assert err.isError and "merge_external" in err.content[0].text
    saved = payload(call("map_save", {"path": path, "validate": False, "rebuild_script": "never", "merge_external": True}))
    assert saved["saved"] and saved["merged"]["taken"] == ["war3map.wpm"] and saved["merged"]["kept"] == ["war3map.j"]
    arc = Archive.open(src)
    assert (arc.read("war3map.j"), arc.read("war3map.wpm")) == (b"mine", b"editor path")
    payload(call("map_close", {"path": path}))


@needs_install
def test_map_save_compiles_the_script(tmp_path):
    maps = [p for p in ladder_maps() if Archive.open(p).read("war3map.j") is not None]
    if not maps:
        pytest.skip("no JASS ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    path = str(src)
    payload(call("map_open", {"path": path}))
    payload(call("triggers_edit", {"path": path, "ops": [
        {"op": "trigger", "name": "Broken", "script": "call NoSuchNativeHere()\n"}]}))
    refused = call("map_save", {"path": path})
    assert refused.isError and "does not compile" in refused.content[0].text
    payload(call("triggers_edit", {"path": path, "ops": [
        {"op": "script_replace", "name": "Broken", "old": "call NoSuchNativeHere()", "new": 'call BJDebugMsg("ok")'}]}))
    saved = payload(call("map_save", {"path": path}))
    assert saved["saved"] and saved["validation"]["script"]["ok"]
    payload(call("map_close", {"path": path}))


def test_batch_runs_several_tools_in_one_call(tmp_path):
    """The chains that always go together (edit, rebuild, check) in one round trip."""
    src = tmp_path / "batch.w3x"
    src.write_bytes(write_archive({"war3map.j": b"// script"}))
    out = payload(call("wc3_batch", {"calls": [
        {"tool": "map_open", "args": {"path": str(src)}},
        {"tool": "map_file_read", "args": {"path": str(src), "name": "war3map.j"}},
        {"tool": "map_status", "args": {"path": str(src)}}]}))
    assert out["ran"] == 3 and out["failed"] == 0
    assert [r["tool"] for r in out["results"]] == ["map_open", "map_file_read", "map_status"]
    assert out["results"][1]["result"]["content"] == "// script"
    stopped = payload(call("wc3_batch", {"calls": [
        {"tool": "map_status", "args": {"path": str(tmp_path / "gone.w3x")}},
        {"tool": "map_status", "args": {"path": str(src)}}]}))
    assert stopped["ran"] == 1 and stopped["failed"] == 1
    assert stopped["results"][0]["error"]["code"] == "not_open"
    both = payload(call("wc3_batch", {"stop_on_error": False, "calls": [
        {"tool": "map_status", "args": {"path": str(tmp_path / "gone.w3x")}},
        {"tool": "map_status", "args": {"path": str(src)}}]}))
    assert both["ran"] == 2 and both["failed"] == 1 and both["results"][1]["ok"]
    for calls, code in (([{"tool": "no_such_tool", "args": {}}], "not_found"),
                        ([{"tool": "wc3_batch", "args": {"calls": []}}], "not_found"),
                        ([{"tool": "terrain_render", "args": {"path": str(src)}}], "bad_value"),
                        ([{"tool": "map_status", "args": "path"}], "bad_value"),
                        ([], "bad_value")):
        err = call("wc3_batch", {"calls": calls})
        assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == code, calls
    bad_args = payload(call("wc3_batch", {"calls": [{"tool": "map_status", "args": {"nope": 1}}]}))
    assert bad_args["results"][0]["error"]["code"] == "bad_value"
    zero = payload(call("wc3_batch", {"calls": [{"tool": "wc3_help"}]}))   # a tool that takes nothing needs no args
    assert zero["results"][0]["ok"] and zero["results"][0]["result"]["topics"]
    # a call without path takes the batch's last path, or the only open map
    inherited = payload(call("wc3_batch", {"calls": [{"tool": "map_status", "args": {}},
                                                    {"tool": "map_file_read", "args": {"name": "war3map.j"}}]}))
    assert inherited["failed"] == 0 and inherited["results"][1]["result"]["content"] == "// script"
    payload(call("map_close", {"path": str(src)}))


def test_a_snapshot_without_a_label_names_the_parameter(tmp_path):
    src = tmp_path / "snap.w3x"
    src.write_bytes(write_archive({"war3map.j": b"// script"}))
    payload(call("map_open", {"path": str(src)}))
    err = call("map_snapshot", {"path": str(src), "action": "create"})
    body = json.loads(err.content[0].text.split(": ", 1)[1])
    assert err.isError and body["code"] == "bad_label" and body["message"].startswith("label:")
    payload(call("map_close", {"path": str(src)}))


def test_help_pages_hold_what_the_descriptions_left_out():
    listing = payload(call("wc3_help", {}))
    assert "placed_edit" in listing["topics"] and "game_test" in listing["topics"]
    page = payload(call("wc3_help", {"topic": "placed_edit"}))
    assert page["topic"] == "placed_edit" and '"op": "forest"' in page["text"] and "scatter" in page["text"]
    unknown = payload(call("wc3_help", {"topic": "nope"}))
    assert unknown["unknown_topic"] == "nope" and unknown["topics"]
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    for name in listing["topics"]:
        # a page named after a tool is pointed at from that tool; a topic page (terrain_landscape) from its tool too
        holder = name if name in tools else {"terrain_landscape": "terrain_edit", "replays": "replay_read"}[name]
        assert f'wc3_help("{name}")' in tools[holder].description, name


def test_gameplay_constants_through_the_tools(tmp_path):
    path = str(tmp_path / "Constants.w3x")
    payload(call("map_new", {"path": path, "width": 32, "height": 32, "players": 2}))
    try:
        cap = payload(call("constants_get", {"path": path, "keys": ["MaxHeroLevel"]}))["constants"][0]
        assert cap["value"] == "10" and cap["modified"] is False
        written = payload(call("constants_edit", {"path": path, "set": {"MaxHeroLevel": 25}}))
        assert written["changed"] and written["constants"][0]["value"] == "25"
        assert payload(call("constants_get", {"path": path, "modified_only": True}))["count"] == 1
        bad = call("constants_edit", {"path": path, "set": {"MaxHerosLevel": 25}})
        assert bad.isError and "MaxHerosLevel" in bad.content[0].text
    finally:
        call("map_close", {"path": path})


@needs_install
def test_compact_results_for_loops(tmp_path):
    """data_search tells the whole count; placed_list, map_flow and terrain_edit answer only what a loop reads."""
    found = payload(call("data_search", {"kind": "icon", "query": "*BTN*", "limit": 900, "fields": ["id"]}))
    assert found["count"] > 500 and found["returned"] == 500 and found["capped"] and set(found["results"][0]) == {"id"}
    err = call("data_search", {"kind": "unit", "query": "Footman", "fields": ["nope"]})
    assert err.isError and "bad_value" in err.content[0].text
    path = str(tmp_path / "C.w3x")
    payload(call("map_new", {"path": path, "width": 64, "height": 64, "players": 2}))
    payload(call("map_open", {"path": path}))
    starts = payload(call("placed_list", {"path": path, "kind": "start_location", "fields": ["ref", "x"]}))["items"]
    assert starts and set(starts[0]) == {"ref", "x"}
    flow = payload(call("map_flow", {"path": path, "origins": ["start:0"], "targets": ["start:1"]}))
    assert flow["targets"][0]["reachable"] and "route" not in flow["targets"][0]
    assert "route" in payload(call("map_flow", {"path": path, "origins": ["start:0"], "targets": ["start:1"],
                                                "verbose": True}))["targets"][0]
    narrow = payload(call("map_flow", {"path": path, "origins": ["start:0"], "targets": ["start:1"], "min_gap": 64}))
    assert narrow["targets"] == [] and narrow["hidden"] == 1
    edit = payload(call("terrain_edit", {"path": path, "ops": [{"op": "cliff", "rect": [-512, -512, 512, 512],
                                                                "level": 6}]}))
    assert edit["cliffs"]["ops"] == 1 and edit["cliffs"]["blended"] > 0


def test_image_crop_enlarges_part_of_a_picture(tmp_path):
    from PIL import Image as PILImage

    shot = tmp_path / "shot.png"
    PILImage.new("RGB", (100, 80), (0, 0, 255)).save(shot)
    result = call("image_crop", {"path": str(shot), "rect": [10, 20, 5, 4], "scale": 3})
    assert not result.isError and result.content[0].type == "image"
    assert "shot_crop_10_20.png" in result.content[1].text
    with PILImage.open(tmp_path / "shot_crop_10_20.png") as im:
        assert im.size == (15, 12)
    assert call("image_crop", {"path": str(shot), "rect": [0, 0, 0, 4]}).isError


@needs_install
def test_editor_dropped_names_fields_a_save_left_out(tmp_path):
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops.newmap import new_map
    from wc3mcp.ops.objdata import objdata_edit
    from corpus import _storage

    catalog = Catalog(_storage(), balance=None)
    p = new_map(str(tmp_path / "D.w3x"), catalog, width=32, height=32, players=2)
    objdata_edit(p, catalog, "destructible", [{"op": "create", "base": "LTlt", "id": "B000",
                                               "set": {"bmis": 0.5, "bmas": 2.0}}])
    names = [f["name"] for f in p.list_files() if f["name"].lower().endswith(".w3b")]
    before = {n: p.read(n) for n in names}
    objdata_edit(p, catalog, "destructible", [{"op": "reset", "id": "B000", "fields": ["bmis", "bmas"]}])
    after = {n: p.read(n) for n in names}
    dropped = server._editor_dropped(before, after, catalog)
    assert {(d["id"], d["field"]) for d in dropped} == {("B000", "bmis"), ("B000", "bmas")}
    assert server._editor_dropped(before, before, catalog) == []
    # a field stored with the base object's own value is no loss when the editor leaves it out
    default = catalog.get("destructible", "LTlt")["fields"]["bmas"]["value"]
    objdata_edit(p, catalog, "destructible", [{"op": "create", "base": "LTlt", "id": "B001", "set": {"bmas": default}}])
    before = {n: p.read(n) for n in names}
    objdata_edit(p, catalog, "destructible", [{"op": "reset", "id": "B001", "fields": ["bmas"]}])
    assert server._editor_dropped(before, {n: p.read(n) for n in names}, catalog) == []


def test_closing_an_editor_that_does_not_run_is_not_an_error(monkeypatch):
    from wc3mcp.errors import ToolError

    def close(discard=False):
        raise ToolError("editor_not_running", "no World Editor is running")

    monkeypatch.setattr(server.desktop_editor.EDITOR, "close", close)
    assert payload(call("editor_map", {"action": "close"})) == {"closed": False, "running": False}


def test_probe_functions_come_from_one_place():
    err = call("game_test", {"path": "x.w3x", "probe_functions": "a", "probe_functions_file": "b.j"})
    assert err.isError and "not both" in err.content[0].text


def test_game_test_reads_probe_helpers_from_a_path_or_the_probe_file_beside_it(monkeypatch, tmp_path):
    seen = {}

    def build(path, run, catalog, opened, seconds, script, functions, init):
        seen["functions"] = functions
        return tmp_path / "probe.w3x"

    monkeypatch.setattr(server.probe_ops, "build", build)
    monkeypatch.setattr(server.desktop_game.GAME, "test", lambda target, **kw: {"results": {}, "pid": 1})
    helpers = tmp_path / "helpers.j"
    helpers.write_text("function H takes nothing returns nothing\nendfunction\n")
    out = payload(call("game_test", {"path": str(tmp_path / "m.w3x"), "probe_functions": str(helpers)}))
    assert seen["functions"].startswith("function H") and out["server_version"] == server.__version__
    probe = tmp_path / "duel.j"
    probe.write_text("call ProbeReport(\"x\")\n")
    (tmp_path / "duel.functions.j").write_text("function G takes nothing returns nothing\nendfunction\n")
    out = payload(call("game_test", {"path": str(tmp_path / "m.w3x"), "probe_script_file": str(probe)}))
    assert seen["functions"].startswith("function G") and out["probe_functions_file"].endswith("duel.functions.j")


def test_game_test_saves_the_loading_screenshot(monkeypatch, tmp_path):
    monkeypatch.setenv("WC3MCP_HOME", str(tmp_path))
    seen = {}

    def test(target, **kw):
        seen.update(kw)
        return {"results": {}, "pid": 5, "loading_screenshot": b"png"}

    monkeypatch.setattr(server.desktop_game.GAME, "test", test)
    out = payload(call("game_test", {"path": str(tmp_path / "m.w3x"), "loading_screenshot": True}))
    assert seen["loading_shot"] is True and Path(out["loading_screenshot"]).read_bytes() == b"png"
    assert out["loading_screenshot"].endswith("game-5-loading.png")


def test_probe_messages_say_whom_they_were_for():
    from wc3mcp.ops.probe import parse

    doc = parse(["message0=hello", "messageto0=all", "message1=for the bot", "messageto1=3"])
    assert doc["messages"] == ["hello", "for the bot"] and doc["message_to"] == ["all", "3"]


def test_game_status_shows_what_a_long_probe_reported_so_far(monkeypatch, tmp_path):
    monkeypatch.setenv("WC3MCP_DOCUMENTS", str(tmp_path))
    partial = server.desktop_game._result_path(server.probe_ops.PARTIAL)
    partial.parent.mkdir(parents=True)
    partial.write_text('function PreloadFiles takes nothing returns nothing\n\tcall Preload( "report=duel 3 of 24" )\n'
                       "endfunction\n")
    monkeypatch.setattr(server.desktop_game.GAME, "run", {"result": None, "meta": {"probe": True}, "started": 0.0})
    monkeypatch.setattr(server.desktop_game.GAME, "status", lambda: {"run": {"state": "running"}})
    run = payload(call("game_status", {}))["run"]
    assert run["partial"]["reports"] == ["duel 3 of 24"]


def test_game_status_shows_an_open_dialog_of_a_running_run(monkeypatch):
    runner = server.desktop_game.Game()
    runner.run = {"map": "m.w3x", "started": time.time(), "timeout": 60, "results": [], "written": [], "result": None,
                  "error": None, "meta": {}, "dialog": {"first_at": 3.0, "count": 1},
                  "thread": type("T", (), {"is_alive": lambda s: True})()}
    monkeypatch.setattr(server.desktop_game, "GAME", runner)
    monkeypatch.setattr(server.desktop_game.Game, "status", lambda self: {"run": self.run_status()})
    run = payload(call("game_status", {}))["run"]
    assert run["dialog_open"]["first_at"] == 3.0 and "pauses a single-player game" in run["dialog_open"]["note"]


def test_a_finished_probe_gets_the_lines_reported_after_its_report(monkeypatch, tmp_path):
    monkeypatch.setenv("WC3MCP_DOCUMENTS", str(tmp_path))
    partial = server.desktop_game._result_path(server.probe_ops.PARTIAL)
    partial.parent.mkdir(parents=True)
    partial.write_text('function PreloadFiles takes nothing returns nothing\n\tcall Preload( "report=game 1" )\n'
                       '\tcall Preload( "report=game 2" )\nendfunction\n')
    done = server._finish_test({"results": {server.probe_ops.REPORT: ["probe=ok", "report=game 1"]}}, True)
    assert done["probe"]["reports"] == ["game 1", "game 2"] and done["probe"]["merged_from_partial"]
    early = server._finish_test({"results": {}}, True)   # ended before the report: the partial file is the answer
    assert early["probe"]["partial"] and early["probe"]["reports"] == ["game 1", "game 2"] and "hint" not in early


def test_game_status_waits_for_a_run_to_end(monkeypatch):
    polls = iter([True, True, False])
    run = {"result": None, "meta": {}, "started": 0.0, "thread": type("T", (), {"is_alive": lambda s: next(polls)})()}
    monkeypatch.setattr(server.desktop_game.GAME, "run", run)
    monkeypatch.setattr(server.desktop_game.GAME, "status", lambda: {"run": {"state": "done"}})
    monkeypatch.setattr(server.time, "sleep", lambda s: None)
    assert payload(call("game_status", {"wait": 30}))["run"]["state"] == "done"
    assert next(polls, None) is None   # it polled until the thread ended


def test_game_status_keeps_a_long_partial_report_small():
    partial = {"reports": [f"event {i}" for i in range(1000)] + ["death 7"],
               "messages": ["a", "b", "death c"], "message_to": ["all", "0", "3"]}
    out = server._trim_partial(partial, 5, None)
    assert out["reports"] == ["event 996", "event 997", "event 998", "event 999", "death 7"]
    assert out["left_out"] == {"reports": 996} and out["messages"] == ["a", "b", "death c"]
    out = server._trim_partial({"reports": ["x", "death 1"], "messages": ["a", "death c"],
                                "message_to": ["all", "3"]}, 100, "death")
    assert out["reports"] == ["death 1"] and out["messages"] == ["death c"] and out["message_to"] == ["3"]


def test_a_round_trip_can_end_with_the_editor_closed(monkeypatch):
    editor = server.desktop_editor.EDITOR
    monkeypatch.setattr(editor, "status", lambda: {"map": None})
    monkeypatch.setattr(editor, "save", lambda: {"saved": True, "map": None})
    monkeypatch.setattr(editor, "quit", lambda discard=False, force=False: {"quit": True})
    out = payload(call("editor_map", {"action": "save", "quit_after": True}))
    assert out["saved"] and out["quit"] == {"quit": True}


def test_game_regress_reports_verdicts_that_changed_since_the_last_run(monkeypatch, tmp_path):
    suite = tmp_path / "suite"
    suite.mkdir()
    for name in ("a.j", "b.j"):
        (suite / name).write_text("call ProbeReport(\"x\")\n")
    (suite / "a.functions.j").write_text("function F takes nothing returns nothing\nendfunction\n")   # not a probe
    verdicts = [{"a.j": {"swap": True, "flag": True}, "b.j": {"hp": True}},
                {"a.j": {"swap": False, "flag": True}, "b.j": {}}]
    seen = []

    def fake(path, **kw):
        seen.append(Path(kw["probe_script_file"]).name)
        checks = verdicts[0][seen[-1]]
        failed = sorted(n for n, ok in checks.items() if not ok)
        return {"probe": {"checks": checks, "checks_failed": failed, "checks_passed": len(checks) - len(failed)} if checks else None,
                "hint": "no report"}

    monkeypatch.setitem(server.TOOLS, "game_test", fake)
    first = payload(call("game_regress", {"map": "m.w3x", "suite": str(suite)}))
    assert seen == ["a.j", "b.j"] and first["changed"] == [] and "previous" not in first
    assert first["summary"]["checks_passed"] == 3 and first["game_version"].count(".") == 3
    verdicts.pop(0)
    seen.clear()
    time.sleep(1.1)   # results files are named by the second
    second = payload(call("game_regress", {"map": "m.w3x", "suite": str(suite)}))
    assert second["changed"] == [{"file": "a.j", "check": "swap", "was": True, "now": False},
                                 {"file": "b.j", "check": "hp", "was": True, "now": None}]
    assert second["files"][0]["checks_failed"] == ["swap"] and second["files"][1]["errors"] == ["no report"]
    assert second["previous"]["results"] == Path(first["saved"]).name and len(list((suite / "results").glob("*.json"))) == 2
    seen.clear()
    payload(call("game_regress", {"map": "m.w3x", "suite": str(suite), "stop_on_fail": True}))
    assert seen == ["a.j"]   # a.j failed a check, so b.j never launched


def test_game_close_answers_with_a_finished_run_result(monkeypatch, tmp_path):
    """A run that game_close ends still holds its screenshots as bytes: the answer has to be the finished result."""
    import json

    monkeypatch.setenv("WC3MCP_HOME", str(tmp_path))
    game = server.desktop_game.GAME
    job = {"result": {"pid": 7, "results": {}, "missing": [], "screenshots": [bytes([137, 80, 78, 71, 255])], "screenshot": None},
           "meta": {"probe": False}, "error": None, "thread": None, "map": "m.w3x", "started": 0.0, "timeout": 10,
           "results": [], "written": []}
    monkeypatch.setattr(game, "run", job)
    monkeypatch.setattr(game, "close", lambda: {"closed": [7], "running": False, "run": game.run_status()})
    out = payload(call("game_close", {}))
    json.dumps(out)
    assert out["run"]["state"] == "done" and all(isinstance(s, str) for s in out["run"]["result"]["screenshots"])


def test_a_brief_result_drops_logs_and_messages_and_sums_up_the_screenshots(tmp_path):
    result = {"seconds": 90.0, "pid": 7, "results": {"x.txt": ["a=1"]}, "missing": [], "exited_early": False,
              "crash": None, "log": ["x"] * 200, "focus": {}, "screenshots": [str(tmp_path / f"game-7-{i}.png") for i in range(3)],
              "screenshot_times": [0.0, 3.1, 6.0],
              "probe": {"probe": "ok", "player0.units": 5, "messages": ["m"] * 50, "message_to": ["all"] * 50,
                        "reports": [f"r{i}" for i in range(300)], "checks": {"a": True},
                        "marks": [{"name": "cast", "time": 3.0}]}}
    server._place_marks(result)
    assert result["probe"]["marks"][0]["nearest_screenshot"].endswith("game-7-1.png")
    out = server._brief_result(result, 5, None)
    assert "log" not in out and "focus" not in out and out["results"] == {"x.txt": ["a=1"]}
    assert out["screenshots"] == {"dir": str(tmp_path), "prefix": "game-7-", "count": 3, "times": [0.0, 3.1, 6.0]}
    assert "messages" not in out["probe"] and "player0.units" not in out["probe"]
    assert out["probe"]["reports"] == ["r295", "r296", "r297", "r298", "r299"] and out["probe"]["checks"] == {"a": True}
    assert len(result["probe"]["reports"]) == 300   # the full result is untouched


def test_a_named_screenshot_is_saved_and_tied_to_its_mark(monkeypatch, tmp_path):
    monkeypatch.setenv("WC3MCP_HOME", str(tmp_path))
    monkeypatch.setenv("WC3MCP_DOCUMENTS", str(tmp_path))
    done = server._finish_test({"pid": 9, "named_screenshots": [{"name": "cast burst", "t": 4.0, "image": b"png"}],
                                "results": {server.probe_ops.REPORT: ["probe=ok", "mark=4.000:cast burst"]}}, True)
    shot = done["named_screenshots"][0]
    assert shot["file"].endswith("game-9-0-cast_burst.png") and "image" not in shot
    assert done["probe"]["marks"] == [{"name": "cast burst", "time": 4.0, "screenshot": shot["file"]}]
