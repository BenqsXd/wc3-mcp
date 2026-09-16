"""game_test(probe=true): a throwaway copy of the map with one trigger that reports what the running game sees, so a
caller can check that a map loads and runs without adding a reporting trigger to the map itself."""
import shutil
from pathlib import Path

from ..errors import ToolError
from ..project.workspace import MapProject
from . import script as script_ops
from . import terrain as terrain_ops
from .triggers import triggers_edit

NAME = "wc3mcpProbe"
REPORT = "wc3mcp\\probe.txt"
JASS = """function Trig_{name}_Actions takes nothing returns nothing
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
            call Preload("player" + I2S(i) + ".gold=" + I2S(GetPlayerState(Player(i), PLAYER_STATE_RESOURCE_GOLD)))
            call Preload("player" + I2S(i) + ".lumber=" + I2S(GetPlayerState(Player(i), PLAYER_STATE_RESOURCE_LUMBER)))
        endif
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
LUA = """function Trig_{name}_Actions()
    PreloadGenClear()
    PreloadGenStart()
    Preload("probe=ok")
    Preload("seconds={seconds}")
    for i = 0, 11 do
        if GetPlayerSlotState(Player(i)) == PLAYER_SLOT_STATE_PLAYING then
            local g = CreateGroup()
            GroupEnumUnitsOfPlayer(g, Player(i), nil)
            Preload("player" .. i .. ".units=" .. CountUnitsInGroup(g))
            Preload("player" .. i .. ".gold=" .. GetPlayerState(Player(i), PLAYER_STATE_RESOURCE_GOLD))
            Preload("player" .. i .. ".lumber=" .. GetPlayerState(Player(i), PLAYER_STATE_RESOURCE_LUMBER))
            DestroyGroup(g)
        end
    end
    PreloadGenEnd("{report}")
end

function InitTrig_{name}()
    gg_trg_{name} = CreateTrigger()
    TriggerRegisterTimerEvent(gg_trg_{name}, {seconds}, false)
    TriggerAddAction(gg_trg_{name}, Trig_{name}_Actions)
end
"""


def script(language: str, seconds: float) -> str:
    template = LUA if language == "lua" else JASS
    return template.format(name=NAME, seconds=f"{float(seconds):.2f}", report=REPORT.replace("\\", "\\\\"))


def build(source, dest, catalog, project=None, seconds: float = 10.0) -> Path:
    """Write a copy of the map (the open working copy when `project` is given) with the probe trigger in it."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if project is not None:
        project.save(dest=dest, format="mpq" if dest.suffix else "folder")
    else:
        shutil.copyfile(Path(source), dest)
    copy = MapProject.open(dest)
    try:
        language = script_ops.language(copy)
        triggers_edit(copy, catalog, [{"op": "trigger", "name": NAME, "script": script(language, seconds)}])
        script_ops.script_build(copy, catalog)
        checked = script_ops.script_validate(copy, catalog)
        if not checked["ok"]:
            raise ToolError("probe_script_failed", f"the probed map's script does not compile: "
                            f"{checked['errors'][0]['message']}", hint="fix the map script (script_validate)",
                            errors=checked["errors"][:5])
        if not any(f["name"].lower() == "war3mapmap.blp" for f in copy.list_files()):
            copy.write("war3mapMap.blp", terrain_ops.minimap(copy, catalog))   # the game quits on a map without one
        copy.save()
    finally:
        copy.close(discard=True)
    return dest


def parse(lines: list[str]) -> dict:
    """"key=value" report lines as a dict, numbers as numbers."""
    out: dict = {}
    for line in lines:
        key, sep, value = line.partition("=")
        out[key] = (int(value) if sep and value.lstrip("-").isdigit() else value if sep else True)
    return out
