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
# JASS maps: the probe copy routes BJDebugMsg and the text display functions through these, which keep the text for
# the report
JASS_GLOBALS = """    string array wc3mcpProbe_messages
    integer wc3mcpProbe_count = 0
    hashtable wc3mcpProbe_table = null
"""
JASS_MESSAGES = """
function wc3mcpProbe_Keep takes string s returns nothing
    if wc3mcpProbe_count < {limit} then
        set wc3mcpProbe_messages[wc3mcpProbe_count] = SubString(s, 0, 200)
        set wc3mcpProbe_count = wc3mcpProbe_count + 1
    endif
endfunction

function wc3mcpProbe_Msg takes string s returns nothing
    call wc3mcpProbe_Keep(s)
    call BJDebugMsg(s)
endfunction

function wc3mcpProbe_DisplayTextToPlayer takes player p, real x, real y, string s returns nothing
    call wc3mcpProbe_Keep(s)
    call DisplayTextToPlayer(p, x, y, s)
endfunction

function wc3mcpProbe_DisplayTimedTextToPlayer takes player p, real x, real y, real d, string s returns nothing
    call wc3mcpProbe_Keep(s)
    call DisplayTimedTextToPlayer(p, x, y, d, s)
endfunction

function wc3mcpProbe_DisplayTextToForce takes force f, string s returns nothing
    call wc3mcpProbe_Keep(s)
    call DisplayTextToForce(f, s)
endfunction

function wc3mcpProbe_DisplayTimedTextToForce takes force f, real d, string s returns nothing
    call wc3mcpProbe_Keep(s)
    call DisplayTimedTextToForce(f, d, s)
endfunction
"""
# map calls routed through the functions above (the Blizzard.j functions that call each other are left alone)
ROUTED = {"BJDebugMsg": "wc3mcpProbe_Msg", **{name: "wc3mcpProbe_" + name for name in (
    "DisplayTextToPlayer", "DisplayTimedTextToPlayer", "DisplayTextToForce", "DisplayTimedTextToForce")}}
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
    for _, name in ipairs({{"BJDebugMsg", "DisplayTextToPlayer", "DisplayTimedTextToPlayer"}}) do
        local shown = _G[name]
        _G[name] = function(...)
            local args = table.pack(...)
            if #wc3mcpProbe_messages < {limit} then
                table.insert(wc3mcpProbe_messages, string.sub(tostring(args[args.n]), 1, 200))
            end
            return shown(...)
        end
    end
    gg_trg_{name} = CreateTrigger()
    TriggerRegisterTimerEvent(gg_trg_{name}, {seconds}, false)
    TriggerAddAction(gg_trg_{name}, Trig_{name}_Actions)
end
"""


# probe_script: the caller's code runs as Trig_wc3mcpProbe_User while the report file is open; ProbeReport(text)
# writes text in pieces short enough for Preload (report= then report+= lines, joined again by parse);
# ProbeExpect(name, condition) records a pass/fail check, so a run answers with a verdict instead of text;
# ProbeCamera(x, y, distance, seconds) looks at a place and waits there, for game_test's screenshots;
# ProbeStartAI(player, "human.ai") gives an empty slot a melee AI so a run has an opponent, and
# ProbeGold(player, gold, lumber) pays for what the test wants built;
# ProbeCountEvent(playerunitevent, name) counts that event from then on, ProbeEventCount(name) reads the count;
# probe_functions (the caller's own functions) come right before Trig_wc3mcpProbe_User
JASS_USER = """function wc3mcpProbe_Counted takes nothing returns nothing
    local integer key = LoadInteger(wc3mcpProbe_table, 1, GetHandleId(GetTriggeringTrigger()))
    call SaveInteger(wc3mcpProbe_table, 0, key, LoadInteger(wc3mcpProbe_table, 0, key) + 1)
endfunction

function ProbeCountEvent takes playerunitevent e, string name returns nothing
    local trigger t = CreateTrigger()
    if wc3mcpProbe_table == null then
        set wc3mcpProbe_table = InitHashtable()
    endif
    call TriggerRegisterAnyUnitEventBJ(t, e)
    call SaveInteger(wc3mcpProbe_table, 1, GetHandleId(t), StringHash(name))
    call TriggerAddAction(t, function wc3mcpProbe_Counted)
    set t = null
endfunction

function ProbeEventCount takes string name returns integer
    if wc3mcpProbe_table == null then
        return 0
    endif
    return LoadInteger(wc3mcpProbe_table, 0, StringHash(name))
endfunction

function ProbeReport takes string s returns nothing
    local integer i = 200
    call Preload("report=" + SubString(s, 0, 200))
    loop
        exitwhen i >= StringLength(s)
        call Preload("report+=" + SubString(s, i, i + 200))
        set i = i + 200
    endloop
endfunction

function ProbeStartAI takes integer slot, string script returns nothing
    call SetPlayerController(Player(slot), MAP_CONTROL_COMPUTER)
    call StartMeleeAI(Player(slot), script)
    call Preload("ai=" + I2S(slot) + ":" + script)
endfunction

function ProbeGold takes integer slot, integer gold, integer lumber returns nothing
    call SetPlayerState(Player(slot), PLAYER_STATE_RESOURCE_GOLD, gold)
    call SetPlayerState(Player(slot), PLAYER_STATE_RESOURCE_LUMBER, lumber)
endfunction

function ProbeCamera takes real x, real y, real distance, real seconds returns nothing
    call SetCameraPosition(x, y)
    if distance > 0 then
        call SetCameraField(CAMERA_FIELD_TARGET_DISTANCE, distance, 0)
    endif
    call Preload("camera=" + I2S(R2I(x)) + "," + I2S(R2I(y)))
    call TriggerSleepAction(seconds)
endfunction

function ProbeExpect takes string name, boolean ok returns nothing
    if ok then
        call Preload("check=pass:" + name)
    else
        call Preload("check=fail:" + name)
    endif
endfunction

{functions}function Trig_{name}_User takes nothing returns nothing
{body}endfunction

"""
LUA_USER = """wc3mcpProbe_counts = {}

function ProbeCountEvent(e, name)
    local t = CreateTrigger()
    TriggerRegisterAnyUnitEventBJ(t, e)
    TriggerAddAction(t, function() wc3mcpProbe_counts[name] = (wc3mcpProbe_counts[name] or 0) + 1 end)
end

function ProbeEventCount(name)
    return wc3mcpProbe_counts[name] or 0
end

function ProbeReport(s)
    s = tostring(s)
    Preload("report=" .. string.sub(s, 1, 200))
    for i = 201, #s, 200 do
        Preload("report+=" .. string.sub(s, i, i + 199))
    end
end

function ProbeStartAI(slot, script)
    SetPlayerController(Player(slot), MAP_CONTROL_COMPUTER)
    StartMeleeAI(Player(slot), script)
    Preload("ai=" .. slot .. ":" .. script)
end

function ProbeGold(slot, gold, lumber)
    SetPlayerState(Player(slot), PLAYER_STATE_RESOURCE_GOLD, gold)
    SetPlayerState(Player(slot), PLAYER_STATE_RESOURCE_LUMBER, lumber or 0)
end

function ProbeCamera(x, y, distance, seconds)
    SetCameraPosition(x, y)
    if distance and distance > 0 then
        SetCameraField(CAMERA_FIELD_TARGET_DISTANCE, distance, 0)
    end
    Preload("camera=" .. math.floor(x) .. "," .. math.floor(y))
    TriggerSleepAction(seconds or 3)
end

function ProbeExpect(name, ok)
    Preload("check=" .. (ok and "pass:" or "fail:") .. tostring(name))
end

{functions}function Trig_{name}_User()
{body}end

"""


def script(language: str, seconds: float, user: str | None = None, functions: str | None = None) -> str:
    lua = language == "lua"
    template = LUA if lua else JASS
    if functions is not None and user is None:
        user = ""
    call = ("" if user is None else f"    Trig_{NAME}_User()\n" if lua else f"    call Trig_{NAME}_User()\n")
    text = template.format(name=NAME, seconds=f"{float(seconds):.2f}", report=REPORT.replace("\\", "\\\\"),
                           limit=MAX_MESSAGES, call_user=call)
    if user is None:
        return text
    body = "".join(f"    {line}\n" if line.strip() else "\n" for line in user.splitlines())
    own = functions.strip("\n") + "\n\n" if functions else ""
    return ((LUA_USER if lua else JASS_USER).replace("{name}", NAME).replace("{functions}", own)
            .replace("{body}", body) + text)


def route_messages(script_text: str) -> str:
    """war3map.j with the probe's message globals, and every BJDebugMsg call of the map going through
    wc3mcpProbe_Msg (declared first, so any function may call it)."""
    head, sep, body = script_text.partition("endglobals")
    if not sep:
        raise ToolError("probe_script_failed", "the map script has no globals block", hint="script_validate")
    body = re.sub(r"\b(" + "|".join(ROUTED) + r")\b", lambda m: ROUTED[m.group(1)], body)
    return head + JASS_GLOBALS + sep + JASS_MESSAGES.format(limit=MAX_MESSAGES) + body


def build(source, dest, catalog, project=None, seconds: float = 10.0, user: str | None = None,
          functions: str | None = None) -> Path:
    """Write a copy of the map (the open working copy when `project` is given) with the probe trigger in it, running
    the caller's `user` code (JASS or Lua statements, as the map's language) when given, after the caller's own
    `functions`."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if project is not None:
        project.save(dest=dest, format="mpq" if dest.suffix else "folder")
    else:
        shutil.copyfile(Path(source), dest)
    copy = MapProject.open(dest)
    try:
        language = script_ops.language(copy)
        # in its own last category: trigger code is emitted in tree order, so probe_script can call any map function
        triggers_edit(copy, catalog, [{"op": "category", "name": NAME},
                                      {"op": "trigger", "name": NAME, "category": NAME,
                                       "script": script(language, seconds, user, functions)}])
        script_ops.script_build(copy, catalog)
        if language != "lua":
            name = next(n for n in ("war3map.j", "scripts\\war3map.j")
                        if any(f["name"].lower() == n for f in copy.list_files()))
            copy.write(name, route_messages(copy.read(name).decode("utf-8", "replace")).encode("utf-8"))
        checked = script_ops.script_validate(copy, catalog)
        if not checked["ok"]:
            first = checked["errors"][0]
            mine = (user is not None or functions is not None) and first.get("trigger") == NAME
            raise ToolError("probe_script_failed", f"the probed map's script does not compile: {first['message']}",
                            hint="fix probe_script (it runs as the body of Trig_wc3mcpProbe_User; declare locals "
                            "first) or probe_functions (whole functions, placed before it)" if mine
                            else "fix the map script (script_validate)", errors=checked["errors"][:5])
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
        elif key == "camera" and sep:
            out.setdefault("camera", []).append(value)
        elif key == "ai" and sep:
            out.setdefault("ai", []).append(value)
        elif key == "check" and sep:
            verdict, _, name = value.partition(":")
            out.setdefault("checks", {})[name] = verdict == "pass"
        else:
            out[key] = (int(value) if sep and value.lstrip("-").isdigit() else value if sep else True)
    if "checks" in out:   # ProbeExpect: the run's own verdict, so a caller reads pass/fail instead of text
        failed = sorted(name for name, ok in out["checks"].items() if not ok)
        out["checks_failed"] = failed
        out["checks_passed"] = len(out["checks"]) - len(failed)
    return out
