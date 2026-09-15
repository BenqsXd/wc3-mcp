"""The acceptance scenario: a small hero-arena project built only through MCP tool calls (Phase 6 plan)."""
import asyncio
import json
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

from wc3mcp import server

VARIANTS = ("gui", "jass", "lua")
ICON = "war3mapImported\\BTNArenaChampion.blp"
MODEL = "war3mapImported\\ArenaChampion.mdx"


def tool(tool_name: str, /, **args):
    """Call one tool through the in-process MCP client; returns its JSON result."""
    async def run():
        async with create_connected_server_and_client_session(server.mcp._mcp_server) as client:
            return await client.call_tool(tool_name, args)
    result = asyncio.run(run())
    if result.isError:
        raise AssertionError(f"{tool_name} failed: {result.content[0].text}")
    return json.loads(result.content[0].text) if result.content and result.content[0].type == "text" else None


def report_file(variant: str) -> str:
    return f"wc3mcp\\arena_{variant}.txt"


def expected_report(hero: str) -> list[str]:
    return [str(int.from_bytes(hero.encode(), "big")), "3", "1", "token", "arena"]


def _report_jass(hero: str, variant: str) -> list[str]:
    """the report lines, as JASS statements (also the GUI variant's Custom Script actions)"""
    return ["call PreloadGenClear()", "call PreloadGenStart()",
            f"call Preload(I2S(GetUnitTypeId({hero})))",
            f"call Preload(I2S(GetHeroLevel({hero})))",
            f"call Preload(I2S(GetUnitAbilityLevel({hero}, 'A000')))",
            f"if UnitHasItemOfTypeBJ({hero}, 'I000') then", '    call Preload("token")', "endif",
            f"if RectContainsUnit(gg_rct_Arena, {hero}) then", '    call Preload("arena")', "endif",
            'call PreloadGenEnd("' + report_file(variant).replace("\\", "\\\\") + '")']


def _jass_trigger(hero: str) -> str:
    body = [f"call SetHeroLevel({hero}, 3, false)", f"call SelectHeroSkill({hero}, 'A000')",
            f"call UnitAddItemById({hero}, 'I000')"] + _report_jass(hero, "jass")
    return ("function Trig_Arena_Report_Actions takes nothing returns nothing\n"
            + "".join(f"    {line}\n" for line in body) + "endfunction\n\n"
            "function InitTrig_Arena_Report takes nothing returns nothing\n"
            "    set gg_trg_Arena_Report = CreateTrigger(  )\n"
            "    call TriggerAddAction( gg_trg_Arena_Report, function Trig_Arena_Report_Actions )\n"
            "endfunction\n")


def _lua_trigger(hero: str) -> str:
    report = report_file("lua").replace("\\", "\\\\")
    return ("function Trig_Arena_Report_Actions()\n"
            f"    SetHeroLevel({hero}, 3, false)\n"
            f"    SelectHeroSkill({hero}, FourCC('A000'))\n"
            f"    UnitAddItemById({hero}, FourCC('I000'))\n"
            "    PreloadGenClear()\n"
            "    PreloadGenStart()\n"
            f"    Preload(I2S(GetUnitTypeId({hero})))\n"
            f"    Preload(I2S(GetHeroLevel({hero})))\n"
            f"    Preload(I2S(GetUnitAbilityLevel({hero}, FourCC('A000'))))\n"
            f"    if UnitHasItemOfTypeBJ({hero}, FourCC('I000')) then\n"
            '        Preload("token")\n'
            "    end\n"
            f"    if RectContainsUnit(gg_rct_Arena, {hero}) then\n"
            '        Preload("arena")\n'
            "    end\n"
            f'    PreloadGenEnd("{report}")\n'
            "end\n\n"
            "function InitTrig_Arena_Report()\n"
            "    gg_trg_Arena_Report = CreateTrigger()\n"
            "    TriggerAddAction(gg_trg_Arena_Report, Trig_Arena_Report_Actions)\n"
            "end\n")


def build_ai(folder: Path) -> Path:
    wai = folder / "HeroArena.wai"
    skills = ["AHhb", "AHds", "AHhb", "AHad", "AHhb", "AHre", "AHds", "AHad", "AHds", "AHad"]
    tool("ai_edit", path=str(wai), ops=[
        {"op": "set", "path": "name", "value": "Arena Rivals"},
        {"op": "set", "path": "heroes[0]", "value": {"id": "Hpal", "skills": [skills] * 3}},
        {"op": "append", "path": "build", "value": {"type": "unit", "id": "hbar", "town": "main"}},
        {"op": "append", "path": "build", "value": {"type": "unit", "id": "hero1"}},
        {"op": "append", "path": "build", "value": {"type": "unit", "id": "hfoo"}},
        {"op": "append", "path": "build", "value": {"type": "unit", "id": "hfoo"}},
        {"op": "set", "path": "groups[0].units", "value": [{"id": "hero1", "quantity": 1},
                                                          {"id": "hfoo", "quantity": 2, "maximum": 4}]},
        {"op": "set", "path": "attack.waves", "value": [{"group": 0, "delay": 30}]}])
    return wai


def build_map(path: Path, variant: str, wai: Path) -> dict:
    p = str(path)
    tool("map_new", path=p, width=64, height=64, tileset="L", name=f"Hero Arena ({variant.upper()})", author="wc3mcp",
         players=2, script_language="lua" if variant == "lua" else "jass")
    tool("info_edit", path=p, ops=[{"op": "set", "path": "description",
                                    "value": "A small hero arena built through the wc3mcp tools."}])
    tool("terrain_edit", path=p, ops=[{"op": "raise", "x": 0, "y": 0, "radius": 700, "amount": 64},
                                      {"op": "paint", "x": 0, "y": 0, "radius": 500, "tile": "Lgrs"}])
    tool("elements_edit", path=p, kind="region", ops=[
        {"op": "upsert", "name": "Arena", "left": -512, "bottom": -512, "right": 512, "top": 512}])
    tool("asset_edit", source={"game": "ReplaceableTextures/CommandButtons/BTNFootman.dds"}, dest={"map": p, "name": ICON},
         ops=[{"op": "tint", "color": [230, 180, 40], "strength": 0.5}, {"op": "icon", "kind": "BTN"}])
    tool("asset_edit", source={"game": "Units/Human/Footman/Footman.mdx"}, dest={"map": p, "name": MODEL},
         ops=[{"op": "scale", "factor": 1.3}, {"op": "team_color", "material": 0},
              {"op": "add_attachment", "name": "Champion Crown Ref", "parent": 0, "position": [0, 0, 160]}])
    ability = tool("objdata_edit", path=p, kind="ability", ops=[
        {"op": "create", "base": "AHhb", "set": {"Name": "Arena Light"}}])["created"][0]
    hero = tool("objdata_edit", path=p, kind="unit", ops=[
        {"op": "create", "base": "Hpal", "set": {"Name": "Arena Champion", "uico": ICON, "umdl": MODEL,
                                                  "uhab": ability}}])["created"][0]
    item = tool("objdata_edit", path=p, kind="item", ops=[
        {"op": "create", "base": "ratc", "set": {"Name": "Arena Token"}}])["created"][0]
    tool("placed_edit", path=p, ops=[
        {"op": "add", "kind": "unit", "type": hero, "x": 0, "y": 0, "owner": 0},
        {"op": "add", "kind": "unit", "type": "nogr", "x": 700, "y": 700, "owner": 24},
        {"op": "add", "kind": "item", "type": item, "x": 128, "y": -128}])
    champion = tool("placed_list", path=p, kind="unit", type_id=hero)["items"][0]["script_name"]
    trigger = {"op": "trigger", "name": "Arena Report"}
    if variant == "gui":
        trigger["events"] = [{"fn": "MapInitializationEvent"}]
        trigger["actions"] = [
            {"fn": "SetHeroLevel", "args": [{"var": champion}, 3, {"preset": "ShowHideHide"}]},
            {"fn": "SelectHeroSkill", "args": [{"var": champion}, ability]},
            {"fn": "UnitAddItemByIdSwapped", "args": [item, {"var": champion}]},
        ] + [{"fn": "CustomScriptCode", "args": [line.strip()]} for line in _report_jass(champion, "gui")]
    else:
        trigger["script"] = _jass_trigger(champion) if variant == "jass" else _lua_trigger(champion)
        trigger["run_on_init"] = True
    tool("triggers_edit", path=p, ops=[trigger])
    tool("ai_export", path=str(wai), map_path=p, player=1)
    tool("script_build", path=p)
    validation = tool("script_validate", path=p)
    assert validation["ok"], validation
    checks = tool("map_validate", path=p)
    assert checks["errors"] == [], checks["errors"]
    tool("map_save", path=p)
    tool("map_close", path=p)
    return {"path": path, "hero": hero, "ability": ability, "item": item, "champion": champion}


def build(folder: Path) -> dict:
    """Build the three map variants and the campaign under folder."""
    folder.mkdir(parents=True, exist_ok=True)
    wai = build_ai(folder)
    maps = {v: build_map(folder / f"HeroArena{v.upper() if v != 'lua' else 'Lua'}.w3x", v, wai) for v in VARIANTS}
    campaign = folder / "HeroArena.w3n"
    c = str(campaign)
    tool("campaign_new", path=c, name="Hero Arena", author="wc3mcp")
    tool("campaign_edit", path=c, ops=[
        {"op": "add_map", "source": str(maps["gui"]["path"])},
        {"op": "add_map", "source": str(maps["jass"]["path"])},
        {"op": "append", "path": "buttons", "value": {"chapter": "Chapter One", "title": "The GUI Arena",
                                                      "map": maps["gui"]["path"].name, "visible": True}},
        {"op": "append", "path": "buttons", "value": {"chapter": "Chapter Two", "title": "The JASS Arena",
                                                      "map": maps["jass"]["path"].name, "visible": True}}])
    tool("map_save", path=c)
    tool("map_close", path=c)
    return {"maps": maps, "campaign": campaign, "ai": wai}


def check_map(built: dict, variant: str) -> None:
    """Reopen a built (or editor-saved) map through the tools and check the scenario's pieces."""
    p = str(built["path"])
    tool("map_open", path=p)
    try:
        assert tool("info_get", path=p)["script_language"] == ("lua" if variant == "lua" else "jass")
        for kind, id_ in (("unit", built["hero"]), ("ability", built["ability"]), ("item", built["item"])):
            assert id_ in [o["id"] for o in tool("objdata_list", path=p, kind=kind, custom_only=True)["objects"]]
        assert [r["name"] for r in tool("elements_list", path=p, kind="region")["items"]] == ["Arena"]
        hero, = tool("placed_list", path=p, kind="unit", type_id=built["hero"])["items"]
        assert (hero["owner"], hero["x"], hero["y"], hero["script_name"]) == (0, 0.0, 0.0, built["champion"])
        imports = {i["path"].replace("/", "\\") for i in tool("imports_edit", path=p)["imports"]}
        assert {ICON, MODEL, "war3mapImported\\HeroArena.ai"} <= imports
        triggers = {t["name"]: t["type"] for t in tool("triggers_tree", path=p)["triggers"]}
        assert triggers["Arena Report"] == ("gui" if variant == "gui" else "text")
        assert "Start AI HeroArena" in triggers
        assert tool("map_validate", path=p)["errors"] == []
        assert tool("script_validate", path=p)["ok"]
    finally:
        tool("map_close", path=p, discard=True)


def check_campaign(path: Path) -> None:
    c = str(path)
    tool("map_open", path=c)
    try:
        campaign = tool("campaign_get", path=c)
        assert [b["map"] for b in campaign["buttons"]] == ["HeroArenaGUI.w3x", "HeroArenaJASS.w3x"]
        assert sorted(m["name"] for m in campaign["maps"]) == ["HeroArenaGUI.w3x", "HeroArenaJASS.w3x"]
    finally:
        tool("map_close", path=c, discard=True)
