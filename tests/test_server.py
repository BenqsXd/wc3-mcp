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
            "placed_edit", "terrain_get", "terrain_edit", "terrain_render", "campaign_new", "campaign_get",
            "campaign_edit", "ai_get", "ai_edit", "ai_export", "asset_info", "asset_convert", "asset_edit",
            "asset_preview", "constants_get", "constants_edit"}


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
    assert both["objects"][1]["orders"]["data"] == {"aord": "thunderbolt"}
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
        holder = name if name in tools else "terrain_edit"
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
