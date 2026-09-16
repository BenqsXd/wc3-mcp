"""game_test(probe=true): a throwaway copy of the map with one trigger that reports what the running game sees, so a
caller can check that a map loads and runs without adding a reporting trigger to the map itself."""
import re
import shutil
from pathlib import Path

from ..errors import ToolError
from ..project.workspace import MapProject
from . import script as script_ops
from . import terrain as terrain_ops
from .triggers import triggers_edit

NAME = "wc3mcpProbe"
REPORT = "wc3mcp\\probe.txt"
MAX_MESSAGES = 50
# JASS maps: the probe copy routes BJDebugMsg through this function, which keeps the text for the report
JASS_GLOBALS = """    string array wc3mcpProbe_messages
    integer wc3mcpProbe_count = 0
"""
JASS_MESSAGES = """
function wc3mcpProbe_Msg takes string s returns nothing
    if wc3mcpProbe_count < {limit} then
        set wc3mcpProbe_messages[wc3mcpProbe_count] = SubString(s, 0, 200)
        set wc3mcpProbe_count = wc3mcpProbe_count + 1
    endif
    call BJDebugMsg(s)
endfunction
"""
JASS = """function Trig_{name}_Hero takes nothing returns boolean
    return IsUnitType(GetFilterUnit(), UNIT_TYPE_HERO)
endfunction

function Trig_{name}_Actions takes nothing returns nothing
    local integer i = 0
    local group g = CreateGroup()
    call PreloadGenClear()
    call PreloadGenStart()
    call Preload("probe=ok")
    call Preload("seconds={seconds}")
    loop
        exitwhen i > 11
        if GetPlayerSlotState(Player(i)) == PLAYER_SLOT_STATE_PLAYING then
            call GroupEnumUnitsOfPlayer(g, Player(i), null)
            call Preload("player" + I2S(i) + ".units=" + I2S(CountUnitsInGroup(g)))
            call GroupClear(g)
            call GroupEnumUnitsOfPlayer(g, Player(i), Condition(function Trig_{name}_Hero))
            call Preload("player" + I2S(i) + ".heroes=" + I2S(CountUnitsInGroup(g)))
            call GroupClear(g)
            call Preload("player" + I2S(i) + ".gold=" + I2S(GetPlayerState(Player(i), PLAYER_STATE_RESOURCE_GOLD)))
            call Preload("player" + I2S(i) + ".lumber=" + I2S(GetPlayerState(Player(i), PLAYER_STATE_RESOURCE_LUMBER)))
        endif
        set i = i + 1
    endloop
{call_user}    set i = 0
    loop
        exitwhen i >= wc3mcpProbe_count
        call Preload("message" + I2S(i) + "=" + wc3mcpProbe_messages[i])
        set i = i + 1
    endloop
    call PreloadGenEnd("{report}")
    call DestroyGroup(g)
    set g = null
endfunction

function InitTrig_{name} takes nothing returns nothing
    set gg_trg_{name} = CreateTrigger(  )
    call TriggerRegisterTimerEvent(gg_trg_{name}, {seconds}, false)
    call TriggerAddAction(gg_trg_{name}, function Trig_{name}_Actions)
endfunction
"""
LUA = """wc3mcpProbe_messages = {{}}

function Trig_{name}_Actions()
    PreloadGenClear()
    PreloadGenStart()
    Preload("probe=ok")
    Preload("seconds={seconds}")
    for i = 0, 11 do
        if GetPlayerSlotState(Player(i)) == PLAYER_SLOT_STATE_PLAYING then
            local g = CreateGroup()
            GroupEnumUnitsOfPlayer(g, Player(i), nil)
            Preload("player" .. i .. ".units=" .. CountUnitsInGroup(g))
            GroupClear(g)
            GroupEnumUnitsOfPlayer(g, Player(i), Filter(function() return IsUnitType(GetFilterUnit(), UNIT_TYPE_HERO) end))
            Preload("player" .. i .. ".heroes=" .. CountUnitsInGroup(g))
            Preload("player" .. i .. ".gold=" .. GetPlayerState(Player(i), PLAYER_STATE_RESOURCE_GOLD))
            Preload("player" .. i .. ".lumber=" .. GetPlayerState(Player(i), PLAYER_STATE_RESOURCE_LUMBER))
            DestroyGroup(g)
        end
    end
{call_user}    for i, text in ipairs(wc3mcpProbe_messages) do
        Preload("message" .. (i - 1) .. "=" .. text)
    end
    PreloadGenEnd("{report}")
end

function InitTrig_{name}()
    local shown = BJDebugMsg
    BJDebugMsg = function(s)
        if #wc3mcpProbe_messages < {limit} then
            table.insert(wc3mcpProbe_messages, string.sub(s, 1, 200))
        end
        shown(s)
    end
    gg_trg_{name} = CreateTrigger()
    TriggerRegisterTimerEvent(gg_trg_{name}, {seconds}, false)
    TriggerAddAction(gg_trg_{name}, Trig_{name}_Actions)
end
"""


# probe_script: the caller's code runs as Trig_wc3mcpProbe_User while the report file is open; ProbeReport(text)
# writes text in pieces short enough for Preload (report= then report+= lines, joined again by parse)
JASS_USER = """function ProbeReport takes string s returns nothing
    local integer i = 200
    call Preload("report=" + SubString(s, 0, 200))
    loop
        exitwhen i >= StringLength(s)
        call Preload("report+=" + SubString(s, i, i + 200))
        set i = i + 200
    endloop
endfunction

function Trig_{name}_User takes nothing returns nothing
{body}endfunction

"""
LUA_USER = """function ProbeReport(s)
    s = tostring(s)
    Preload("report=" .. string.sub(s, 1, 200))
    for i = 201, #s, 200 do
        Preload("report+=" .. string.sub(s, i, i + 199))
    end
end

function Trig_{name}_User()
{body}end

"""


def script(language: str, seconds: float, user: str | None = None) -> str:
    lua = language == "lua"
    template = LUA if lua else JASS
    call = ("" if user is None else f"    Trig_{NAME}_User()\n" if lua else f"    call Trig_{NAME}_User()\n")
    text = template.format(name=NAME, seconds=f"{float(seconds):.2f}", report=REPORT.replace("\\", "\\\\"),
                           limit=MAX_MESSAGES, call_user=call)
    if user is None:
        return text
    body = "".join(f"    {line}\n" if line.strip() else "\n" for line in user.splitlines())
    return (LUA_USER if lua else JASS_USER).replace("{name}", NAME).replace("{body}", body) + text


def route_messages(script_text: str) -> str:
    """war3map.j with the probe's message globals, and every BJDebugMsg call of the map going through
    wc3mcpProbe_Msg (declared first, so any function may call it)."""
    head, sep, body = script_text.partition("endglobals")
    if not sep:
        raise ToolError("probe_script_failed", "the map script has no globals block", hint="script_validate")
    body = re.sub(r"\bBJDebugMsg\b", "wc3mcpProbe_Msg", body)
    return head + JASS_GLOBALS + sep + JASS_MESSAGES.format(limit=MAX_MESSAGES) + body


def build(source, dest, catalog, project=None, seconds: float = 10.0, user: str | None = None) -> Path:
    """Write a copy of the map (the open working copy when `project` is given) with the probe trigger in it, running
    the caller's `user` code (JASS or Lua statements, as the map's language) when given."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if project is not None:
        project.save(dest=dest, format="mpq" if dest.suffix else "folder")
    else:
        shutil.copyfile(Path(source), dest)
    copy = MapProject.open(dest)
    try:
        language = script_ops.language(copy)
        triggers_edit(copy, catalog, [{"op": "trigger", "name": NAME, "script": script(language, seconds, user)}])
        script_ops.script_build(copy, catalog)
        if language != "lua":
            name = next(n for n in ("war3map.j", "scripts\\war3map.j")
                        if any(f["name"].lower() == n for f in copy.list_files()))
            copy.write(name, route_messages(copy.read(name).decode("utf-8", "replace")).encode("utf-8"))
        checked = script_ops.script_validate(copy, catalog)
        if not checked["ok"]:
            first = checked["errors"][0]
            mine = user is not None and first.get("trigger") == NAME
            raise ToolError("probe_script_failed", f"the probed map's script does not compile: {first['message']}",
                            hint="fix probe_script (it runs as the body of Trig_wc3mcpProbe_User; declare locals "
                            "first)" if mine else "fix the map script (script_validate)", errors=checked["errors"][:5])
        if not any(f["name"].lower() == "war3mapmap.blp" for f in copy.list_files()):
            copy.write("war3mapMap.blp", terrain_ops.minimap(copy, catalog))   # the game quits on a map without one
        copy.save()
    finally:
        copy.close(discard=True)
    return dest


def parse(lines: list[str]) -> dict:
    """"key=value" report lines as a dict, numbers as numbers; message<n> lines (BJDebugMsg text) as messages;
    ProbeReport text as reports."""
    out: dict = {"messages": [], "reports": []}
    for line in lines:
        key, sep, value = line.partition("=")
        if re.fullmatch(r"message\d+", key) and sep:
            out["messages"].append(value)
        elif key == "report" and sep:
            out["reports"].append(value)
        elif key == "report+" and sep and out["reports"]:
            out["reports"][-1] += value
        else:
            out[key] = (int(value) if sep and value.lstrip("-").isdigit() else value if sep else True)
    return out
