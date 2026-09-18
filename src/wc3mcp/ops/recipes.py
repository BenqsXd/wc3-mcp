"""Systems every custom map rewrites: damage detection, a unit indexer, respawns, timed waves, a scoreboard, a hero
tavern, quests and camera setup. Each recipe answers with the triggers_edit ops that install it - the GUI variables it
needs and one script trigger - so the map gets a working system in one call instead of four hundred hand-typed lines.

The scripts are JASS the World Editor accepts, they declare their state as GUI variables (a trigger script cannot
declare globals of its own), and every one of them is compiled with pjass by this repo's tests.
"""
import re

from ..errors import ToolError

RAWCODE = re.compile(r"^[A-Za-z0-9_]{4}$")
CATEGORY = "Systems"


def _rawcode(value, path: str) -> str:
    if not isinstance(value, str) or not RAWCODE.match(value):
        raise ToolError("bad_value", f"{path}: expected a 4-character object id, e.g. \"hfoo\"", path=path)
    return value


def _ids(value, path: str) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        raise ToolError("bad_value", f"{path}: expected a list of object ids", path=path)
    return [_rawcode(v, f"{path}[{i}]") for i, v in enumerate(value)]


def _number(value, path: str, low: float = 0.0, high: float = 1e9) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError("bad_value", f"{path}: expected a number", path=path)
    if not low <= float(value) <= high:
        raise ToolError("bad_value", f"{path}: expected a number from {low:g} to {high:g}", path=path)
    return float(value)


def _int(value, path: str, low: int = 0, high: int = 1 << 30) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("bad_value", f"{path}: expected a whole number", path=path)
    if not low <= value <= high:
        raise ToolError("bad_value", f"{path}: expected a whole number from {low} to {high}", path=path)
    return value


def _point(value, path: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ToolError("bad_value", f"{path}: expected [x, y] in world units", path=path)
    return _number(value[0], f"{path}[0]", -1e6), _number(value[1], f"{path}[1]", -1e6)


def _text(value, path: str) -> str:
    if not isinstance(value, str):
        raise ToolError("bad_value", f"{path}: expected text", path=path)
    return value.replace('"', "'").replace("\n", " ")     # the text goes into a JASS string literal


# ---- the recipes -----------------------------------------------------------------------------------------------
def _damage_detection(p: dict, name: str) -> dict:
    """One place every damage event passes through, which is what a custom spell or armour system needs."""
    script = f"""function {name}_Event takes nothing returns nothing
    local unit source = GetEventDamageSource()
    local unit target = GetTriggerUnit()
    local real amount = GetEventDamage()
    // your rules go here: BlzSetEventDamage(amount * 0.5) halves this hit,
    // BlzSetEventDamage(0.0) prevents it, and udg_{name}_Last keeps the last amount for other triggers
    set udg_{name}_Last = amount
    set source = null
    set target = null
endfunction

function Trig_{name}_Actions takes nothing returns nothing
    local trigger t = CreateTrigger()
    call TriggerRegisterAnyUnitEventBJ(t, EVENT_PLAYER_UNIT_DAMAGED)
    call TriggerAddAction(t, function {name}_Event)
    set t = null
endfunction
"""
    return {"variables": [{"op": "variable", "name": f"{name}_Last", "type": "real", "category": CATEGORY}],
            "script": script, "run_on_init": True,
            "uses": ["EVENT_PLAYER_UNIT_DAMAGED", "GetEventDamageSource", "BlzSetEventDamage"],
            "notes": "every hit in the game runs this function, so keep it short; BlzSetEventDamage changes the hit"}


def _unit_indexer(p: dict, name: str) -> dict:
    """A number on every unit, so per-unit data can live in a hashtable or an array instead of a group."""
    script = f"""function {name}_Index takes nothing returns nothing
    local unit u = GetTriggerUnit()
    if GetUnitUserData(u) == 0 then
        set udg_{name}_Count = udg_{name}_Count + 1
        call SetUnitUserData(u, udg_{name}_Count)
    endif
    set u = null
endfunction

function {name}_Data takes unit u returns integer
    return GetUnitUserData(u)
endfunction

function Trig_{name}_Actions takes nothing returns nothing
    local trigger t = CreateTrigger()
    local group g = CreateGroup()
    local unit u
    call TriggerRegisterEnterRectSimple(t, GetPlayableMapRect())
    call TriggerAddAction(t, function {name}_Index)
    if udg_{name}_Table == null then
        set udg_{name}_Table = InitHashtable()
    endif
    call GroupEnumUnitsInRect(g, GetPlayableMapRect(), null)
    loop
        set u = FirstOfGroup(g)
        exitwhen u == null
        call GroupRemoveUnit(g, u)
        set udg_{name}_Count = udg_{name}_Count + 1
        call SetUnitUserData(u, udg_{name}_Count)
    endloop
    call DestroyGroup(g)
    set g = null
    set t = null
endfunction
"""
    return {"variables": [{"op": "variable", "name": f"{name}_Count", "type": "integer", "category": CATEGORY},
                          {"op": "variable", "name": f"{name}_Table", "type": "hashtable", "category": CATEGORY}],
            "script": script, "run_on_init": True,
            "uses": ["SetUnitUserData", "TriggerRegisterEnterRectSimple", "InitHashtable"],
            "notes": (f"{name}_Data(u) gives a unit's index; udg_{name}_Table keeps per-index data "
                      "(SaveInteger(udg_" + name + "_Table, index, 0, value)). A unit that already carries a user "
                      "data value from the object editor keeps it")}


def _respawn(p: dict, name: str) -> dict:
    """Creeps (or any owner's units) that come back where they died, which is what a survival or arena map lives on."""
    delay = _number(p.get("delay", 45), "params.delay", 1, 3600)
    owner = _int(p.get("owner", 24), "params.owner", 0, 27)
    script = f"""function {name}_Back takes nothing returns nothing
    local timer t = GetExpiredTimer()
    local integer id = GetHandleId(t)
    local integer kind = LoadInteger(udg_{name}_Table, id, 0)
    local real x = LoadReal(udg_{name}_Table, id, 1)
    local real y = LoadReal(udg_{name}_Table, id, 2)
    local real face = LoadReal(udg_{name}_Table, id, 3)
    call CreateUnit(Player({owner}), kind, x, y, face)
    call FlushChildHashtable(udg_{name}_Table, id)
    call DestroyTimer(t)
    set t = null
endfunction

function {name}_Died takes nothing returns nothing
    local unit u = GetTriggerUnit()
    local timer t
    if GetOwningPlayer(u) == Player({owner}) and not IsUnitType(u, UNIT_TYPE_STRUCTURE) then
        set t = CreateTimer()
        call SaveInteger(udg_{name}_Table, GetHandleId(t), 0, GetUnitTypeId(u))
        call SaveReal(udg_{name}_Table, GetHandleId(t), 1, GetUnitX(u))
        call SaveReal(udg_{name}_Table, GetHandleId(t), 2, GetUnitY(u))
        call SaveReal(udg_{name}_Table, GetHandleId(t), 3, GetUnitFacing(u))
        call TimerStart(t, {delay:.2f}, false, function {name}_Back)
        set t = null
    endif
    set u = null
endfunction

function Trig_{name}_Actions takes nothing returns nothing
    local trigger t = CreateTrigger()
    if udg_{name}_Table == null then
        set udg_{name}_Table = InitHashtable()
    endif
    call TriggerRegisterAnyUnitEventBJ(t, EVENT_PLAYER_UNIT_DEATH)
    call TriggerAddAction(t, function {name}_Died)
    set t = null
endfunction
"""
    return {"variables": [{"op": "variable", "name": f"{name}_Table", "type": "hashtable", "category": CATEGORY}],
            "script": script, "run_on_init": True,
            "uses": ["EVENT_PLAYER_UNIT_DEATH", "TimerStart", "CreateUnit"],
            "notes": (f"units of player {owner} come back {delay:g} seconds after they die, at the spot they died "
                      "facing the same way; structures are left alone")}


def _waves(p: dict, name: str) -> dict:
    """Timed waves walking from a spawn to a target, growing every round: the spine of a tower defence or a lane map."""
    spawn = _point(p.get("spawn", [0, 0]), "params.spawn")
    target = _point(p.get("target", [0, 1000]), "params.target")
    types = _ids(p.get("types", ["nfoh"]), "params.types")
    interval = _number(p.get("interval", 30), "params.interval", 1, 3600)
    count = _int(p.get("count", 6), "params.count", 1, 200)
    growth = _int(p.get("growth", 1), "params.growth", 0, 50)
    owner = _int(p.get("owner", 11), "params.owner", 0, 27)
    picks = "\n".join(
        f"        {'if' if i == 0 else 'elseif'} kind == {i} then\n            set id = '{t}'"
        for i, t in enumerate(types))
    script = f"""function {name}_Spawn takes nothing returns nothing
    local integer i = 0
    local integer total = {count} + udg_{name}_Round * {growth}
    local integer kind = ModuloInteger(udg_{name}_Round, {len(types)})
    local integer id = '{types[0]}'
    local unit u
    set udg_{name}_Round = udg_{name}_Round + 1
{picks}
        endif
    loop
        exitwhen i >= total
        set u = CreateUnit(Player({owner}), id, {spawn[0]:.1f}, {spawn[1]:.1f}, 0.0)
        call IssuePointOrder(u, "attack", {target[0]:.1f}, {target[1]:.1f})
        set u = null
        set i = i + 1
    endloop
    call DisplayTimedTextToForce(GetPlayersAll(), 8, "Wave " + I2S(udg_{name}_Round) + " of " + I2S(total) + " units")
endfunction

function Trig_{name}_Actions takes nothing returns nothing
    set udg_{name}_Round = 0
    set udg_{name}_Timer = CreateTimer()
    call TimerStart(udg_{name}_Timer, {interval:.2f}, true, function {name}_Spawn)
endfunction
"""
    return {"variables": [{"op": "variable", "name": f"{name}_Round", "type": "integer", "category": CATEGORY},
                          {"op": "variable", "name": f"{name}_Timer", "type": "timer", "category": CATEGORY}],
            "script": script, "run_on_init": True,
            "uses": ["TimerStart", "CreateUnit", "IssuePointOrder"],
            "notes": (f"a wave every {interval:g} seconds from ({spawn[0]:g}, {spawn[1]:g}) to "
                      f"({target[0]:g}, {target[1]:g}), {count} units at first and {growth} more each round, the "
                      f"type cycling through {', '.join(types)}; player {owner} owns them, so ally or unally that "
                      "slot with the players who should fight them")}


def _scoreboard(p: dict, name: str) -> dict:
    """A multiboard with a row per playing slot, refreshed on a timer, which is how a map shows a score at all."""
    title = _text(p.get("title", "Score"), "params.title")
    label = _text(p.get("column", "Points"), "params.column")
    script = f"""function {name}_Refresh takes nothing returns nothing
    local integer i = 0
    local integer row = 1
    if udg_{name}_Board == null then
        return
    endif
    loop
        exitwhen i > 11
        if GetPlayerSlotState(Player(i)) == PLAYER_SLOT_STATE_PLAYING then
            call MultiboardSetItemValueBJ(udg_{name}_Board, 1, row + 1, GetPlayerName(Player(i)))
            call MultiboardSetItemValueBJ(udg_{name}_Board, 2, row + 1, I2S(udg_{name}_Score[i]))
            set row = row + 1
        endif
        set i = i + 1
    endloop
endfunction

function {name}_Build takes nothing returns nothing
    local integer i = 0
    local integer players = 0
    loop
        exitwhen i > 11
        if GetPlayerSlotState(Player(i)) == PLAYER_SLOT_STATE_PLAYING then
            set players = players + 1
        endif
        set i = i + 1
    endloop
    set udg_{name}_Board = CreateMultiboard()
    call MultiboardSetRowCount(udg_{name}_Board, players + 1)
    call MultiboardSetColumnCount(udg_{name}_Board, 2)
    call MultiboardSetTitleText(udg_{name}_Board, "{title}")
    call MultiboardSetItemValueBJ(udg_{name}_Board, 1, 1, "Player")
    call MultiboardSetItemValueBJ(udg_{name}_Board, 2, 1, "{label}")
    call MultiboardSetItemsStyle(udg_{name}_Board, true, false)
    call MultiboardSetItemsWidth(udg_{name}_Board, 0.08)
    call MultiboardDisplay(udg_{name}_Board, true)
    call {name}_Refresh()
    call DestroyTimer(GetExpiredTimer())
endfunction

function Trig_{name}_Actions takes nothing returns nothing
    // a multiboard built during initialisation may not show: start it from a short timer instead
    call TimerStart(CreateTimer(), 0.10, false, function {name}_Build)
    call TimerStart(CreateTimer(), 0.50, true, function {name}_Refresh)
endfunction
"""
    return {"variables": [{"op": "variable", "name": f"{name}_Board", "type": "multiboard", "category": CATEGORY},
                          {"op": "variable", "name": f"{name}_Score", "type": "integer", "array_size": 16,
                           "category": CATEGORY}],
            "script": script, "run_on_init": True,
            "uses": ["CreateMultiboard", "MultiboardDisplay", "TimerStart"],
            "notes": (f"set udg_{name}_Score[player number] anywhere and the board follows within half a second; "
                      "it is built from a 0.1 second timer because a multiboard made during initialisation may not "
                      "display")}


def _hero_tavern(p: dict, name: str) -> dict:
    """A tavern that sells the map's heroes and puts the bought hero where the player starts."""
    heroes = _ids(p.get("heroes", ["Hamg", "Obla", "Edem", "Uwar"]), "params.heroes")
    at = _point(p.get("at", [0, 0]), "params.at")
    tavern = _rawcode(p.get("tavern", "ntav"), "params.tavern")
    script = f"""function {name}_Sold takes nothing returns nothing
    local unit hero = GetSoldUnit()
    local player p = GetOwningPlayer(hero)
    local real x = GetStartLocationX(GetPlayerStartLocation(p))
    local real y = GetStartLocationY(GetPlayerStartLocation(p))
    if IsUnitType(hero, UNIT_TYPE_HERO) then
        call SetUnitPosition(hero, x, y)
        call SelectUnitForPlayerSingle(hero, p)
        call SetCameraPositionForPlayer(p, x, y)
    endif
    set hero = null
    set p = null
endfunction

function Trig_{name}_Actions takes nothing returns nothing
    local trigger t = CreateTrigger()
    set udg_{name}_Tavern = CreateUnit(Player(PLAYER_NEUTRAL_PASSIVE), '{tavern}', {at[0]:.1f}, {at[1]:.1f}, 270.0)
    call TriggerRegisterAnyUnitEventBJ(t, EVENT_PLAYER_UNIT_SELL)
    call TriggerAddAction(t, function {name}_Sold)
    set t = null
endfunction
"""
    return {"variables": [{"op": "variable", "name": f"{name}_Tavern", "type": "unit", "category": CATEGORY}],
            "script": script, "run_on_init": True,
            "uses": ["EVENT_PLAYER_UNIT_SELL", "GetSoldUnit", "SelectUnitForPlayerSingle"],
            "notes": (f"the tavern stands at ({at[0]:g}, {at[1]:g}); the heroes it sells come from its useu field, "
                      f"so set that to {', '.join(heroes)} with objdata_edit (a hero with ureq TALT cannot be "
                      "bought until that requirement is cleared)")}


def _quest(p: dict, name: str) -> dict:
    """A quest in the log, which is where a map explains itself."""
    title = _text(p.get("title", "The Task"), "params.title")
    body = _text(p.get("description", "Hold the line."), "params.description")
    icon = p.get("icon", "ReplaceableTextures\\CommandButtons\\BTNHeroPaladin.blp")
    if not isinstance(icon, str):
        raise ToolError("bad_value", "params.icon: expected an icon path", path="params.icon")
    required = bool(p.get("required", True))
    script = f"""function Trig_{name}_Actions takes nothing returns nothing
    set udg_{name}_Quest = CreateQuest()
    call QuestSetTitle(udg_{name}_Quest, "{title}")
    call QuestSetDescription(udg_{name}_Quest, "{body}")
    call QuestSetIconPath(udg_{name}_Quest, "{icon.replace(chr(92), chr(92) * 2)}")
    call QuestSetRequired(udg_{name}_Quest, {"true" if required else "false"})
    call QuestSetDiscovered(udg_{name}_Quest, true)
    call QuestSetCompleted(udg_{name}_Quest, false)
endfunction
"""
    return {"variables": [{"op": "variable", "name": f"{name}_Quest", "type": "quest", "category": CATEGORY}],
            "script": script, "run_on_init": True,
            "uses": ["CreateQuest", "QuestSetTitle", "QuestSetRequired"],
            "notes": (f"QuestSetCompleted(udg_{name}_Quest, true) marks it done later; QuestSetFailed marks it "
                      "failed")}


def _camera(p: dict, name: str) -> dict:
    """The camera every player starts with: distance, angle and field of view, set per client, which is safe."""
    distance = _number(p.get("distance", 2200), "params.distance", 500, 10000)
    angle = _number(p.get("angle", 304), "params.angle", 180, 360)
    rotation = _number(p.get("rotation", 90), "params.rotation", 0, 360)
    script = f"""function Trig_{name}_Actions takes nothing returns nothing
    // camera settings are what one client sees, so setting them inside GetLocalPlayer does not desync the game
    if GetLocalPlayer() == GetLocalPlayer() then
        call SetCameraField(CAMERA_FIELD_TARGET_DISTANCE, {distance:.1f}, 0.0)
        call SetCameraField(CAMERA_FIELD_ANGLE_OF_ATTACK, {angle:.1f}, 0.0)
        call SetCameraField(CAMERA_FIELD_ROTATION, {rotation:.1f}, 0.0)
    endif
endfunction
"""
    return {"variables": [], "script": script, "run_on_init": True,
            "uses": ["SetCameraField"],
            "notes": ("the stock camera is distance 1650, angle of attack 304 and rotation 90; a wider distance "
                      "suits an arena, a closer one a cinematic")}


def _cinematic(p: dict, name: str) -> dict:
    """A scene: the camera walks its shots while the lines are spoken, and the interface comes back afterwards.
    Cinematics are all timing arithmetic, which is what a generator is for."""
    shots = p.get("shots") or [{"at": [0, 0], "seconds": 4}]
    if not isinstance(shots, list) or not shots:
        raise ToolError("bad_value", "params.shots: expected a list of camera shots", path="params.shots")
    lines = p.get("lines") or []
    if not isinstance(lines, list):
        raise ToolError("bad_value", "params.lines: expected a list of spoken lines", path="params.lines")
    letterbox = bool(p.get("letterbox", True))
    start_after = _number(p.get("start_after", 0), "params.start_after", 0, 3600)
    body, total = [], 0.0
    for i, shot in enumerate(shots):
        if not isinstance(shot, dict):
            raise ToolError("bad_value", f"params.shots[{i}]: expected an object", path=f"params.shots[{i}]")
        at = _point(shot.get("at", [0, 0]), f"params.shots[{i}].at")
        seconds = _number(shot.get("seconds", 4), f"params.shots[{i}].seconds", 0.1, 600)
        distance = _number(shot.get("distance", 1650), f"params.shots[{i}].distance", 300, 20000)
        angle = _number(shot.get("angle", 304), f"params.shots[{i}].angle", 180, 360)
        rotation = _number(shot.get("rotation", 90), f"params.shots[{i}].rotation", 0, 360)
        body.append(f'    // shot {i + 1}')
        body.append(f'    call SetCameraPosition({at[0]:.1f}, {at[1]:.1f})')
        body.append(f'    call SetCameraField(CAMERA_FIELD_TARGET_DISTANCE, {distance:.1f}, 0.0)')
        body.append(f'    call SetCameraField(CAMERA_FIELD_ANGLE_OF_ATTACK, {angle:.1f}, 0.0)')
        body.append(f'    call SetCameraField(CAMERA_FIELD_ROTATION, {rotation:.1f}, 0.0)')
        if shot.get("pan_to") is not None:
            to = _point(shot["pan_to"], f"params.shots[{i}].pan_to")
            pan = _number(shot.get("pan_seconds", seconds), f"params.shots[{i}].pan_seconds", 0.1, 600)
            body.append(f'    call PanCameraToTimed({to[0]:.1f}, {to[1]:.1f}, {pan:.2f})')
        # a line belongs to the shot of the same number, so the words match what is on screen
        if i < len(lines):
            line = lines[i]
            if not isinstance(line, dict):
                raise ToolError("bad_value", f"params.lines[{i}]: expected an object", path=f"params.lines[{i}]")
            speaker = _text(line.get("name", "Narrator"), f"params.lines[{i}].name")
            text = _text(line.get("text", ""), f"params.lines[{i}].text")
            hold = _number(line.get("seconds", seconds), f"params.lines[{i}].seconds", 0.1, 600)
            portrait = line.get("unit")
            unit_id = _rawcode(portrait, f"params.lines[{i}].unit") if portrait else None
            if unit_id:
                body.append(f'    call TransmissionFromUnitTypeWithNameBJ(GetPlayersAll(), Player(0), \'{unit_id}\', '
                            f'"{speaker}", null, null, "{text}", bj_TIMETYPE_SET, {hold:.2f}, false)')
            else:
                body.append(f'    call DisplayTimedTextToForce(GetPlayersAll(), {hold:.2f}, '
                            f'"|cffffcc00{speaker}:|r {text}")')
        body.append(f'    call TriggerSleepAction({seconds:.2f})')
        total += seconds
    script_lines = "\n".join(body)
    start = (f'    call TimerStart(CreateTimer(), {start_after:.2f}, false, function {name}_Start)'
             if start_after > 0 else f'    // call {name}_Play() from your own trigger when the scene should run')
    script = f"""function {name}_Play takes nothing returns nothing
    call ClearTextMessages()
{'    call CinematicModeBJ(true, GetPlayersAll())' if letterbox else '    call DoNothing()'}
{script_lines}
{'    call CinematicModeBJ(false, GetPlayersAll())' if letterbox else '    call DoNothing()'}
    call ResetToGameCamera(1.00)
endfunction

function {name}_Start takes nothing returns nothing
    call DestroyTimer(GetExpiredTimer())
    call {name}_Play()
endfunction

function Trig_{name}_Actions takes nothing returns nothing
{start}
endfunction
"""
    return {"variables": [], "script": script, "run_on_init": True,
            "uses": ["CinematicModeBJ", "SetCameraPosition", "TransmissionFromUnitTypeWithNameBJ",
                     "TriggerSleepAction"],
            "notes": (f"{len(shots)} shot(s) and {len(lines)} line(s), {total:g} seconds in all. "
                      + (f"It starts {start_after:g} seconds into the game." if start_after > 0 else
                         f"Nothing starts it: call {name}_Play() from a later trigger, or pass start_after.")
                      + " A line belongs to the shot with the same number, and a line with a unit id gets that "
                        "unit's portrait")}


RECIPES = {
    "damage_detection": (_damage_detection, "one function every damage event passes through",
                         {"": "no parameters"}),
    "unit_indexer": (_unit_indexer, "a number on every unit, plus a hashtable for per-unit data",
                     {"": "no parameters"}),
    "respawn": (_respawn, "units of one owner come back where they died",
                {"delay": "seconds before they return (45)", "owner": "the player whose units respawn (24, the "
                                                                      "neutral hostile creeps)"}),
    "waves": (_waves, "timed waves walking from a spawn to a target, growing each round",
              {"spawn": "[x, y] they appear at", "target": "[x, y] they walk to", "types": "the unit ids to cycle",
               "interval": "seconds between waves (30)", "count": "units in the first wave (6)",
               "growth": "more units each round (1)", "owner": "the player who owns them (11)"}),
    "scoreboard": (_scoreboard, "a multiboard with a row per player, refreshed twice a second",
                   {"title": "the board's title", "column": "the score column's label"}),
    "hero_tavern": (_hero_tavern, "a tavern that sells heroes and places the bought one at the player's start",
                    {"heroes": "the hero ids it should sell", "at": "[x, y] the tavern stands at",
                     "tavern": "the shop unit id (ntav)"}),
    "quest": (_quest, "a quest in the quest log",
              {"title": "its title", "description": "its text", "icon": "its icon path",
               "required": "whether it counts as required (true)"}),
    "camera": (_camera, "the camera distance, angle and rotation every player starts with",
               {"distance": "target distance (2200)", "angle": "angle of attack (304)",
                "rotation": "rotation (90)"}),
    "cinematic": (_cinematic, "a scene: camera shots with spoken lines and the waits worked out",
                  {"shots": '[{"at": [x, y], "seconds": 4, "distance", "angle", "rotation", "pan_to": [x, y], '
                            '"pan_seconds"}]',
                   "lines": '[{"name": "Arthas", "text": "...", "seconds": 4, "unit": "Hamg"}] - line i belongs to '
                            "shot i",
                   "letterbox": "hide the interface while it runs (true)",
                   "start_after": "seconds into the game it starts, 0 to start it yourself (0)"}),
}


def recipe_list() -> dict:
    """What the library holds, with the parameters of each recipe."""
    return {"recipes": [{"name": name, "does": does, "params": params} for name, (_fn, does, params)
                        in sorted(RECIPES.items())],
            "note": ("script_recipe(name) answers with the triggers_edit ops that install it; install=true puts them "
                     "into the open map and checks the script with pjass")}


def recipe(name: str, params: dict | None = None, trigger: str | None = None) -> dict:
    """The ops that install one recipe: its GUI variables and one script trigger, ready for triggers_edit."""
    if name not in RECIPES:
        raise ToolError("not_found", f"no recipe {name!r}", hint="script_recipe without a name lists them",
                        path="name")
    params = params or {}
    if not isinstance(params, dict):
        raise ToolError("bad_value", "params is an object of the recipe's parameters", path="params")
    build, does, allowed = RECIPES[name]
    unknown = sorted(set(params) - set(allowed) - {""})
    if unknown and "" not in allowed:
        raise ToolError("bad_value", f"{name} takes no {unknown}", hint=", ".join(f"{k}: {v}" for k, v in
                                                                                 allowed.items()), path="params")
    label = trigger or "".join(part.capitalize() for part in name.split("_"))
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", label):
        raise ToolError("bad_value", "trigger: a name that starts with a letter and holds letters, digits and _",
                        path="trigger")
    built = build(params, label)
    ops = [{"op": "category", "name": CATEGORY}] + built["variables"] + [
        {"op": "trigger", "name": label, "category": CATEGORY, "script": built["script"],
         "run_on_init": built["run_on_init"]}]
    return {"recipe": name, "does": does, "trigger": label, "category": CATEGORY, "ops": ops,
            "script": built["script"], "variables": [v["name"] for v in built["variables"]],
            "uses": built["uses"], "notes": built["notes"]}
