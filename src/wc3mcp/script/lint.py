"""Runtime traps in a JASS map script that pjass cannot see: leaks, event data read after a wait, dead triggers,
endless loops, handles used after they were destroyed. Every finding is a heuristic, so it names the function, the
line and what to check; a game run is the only proof, and each rule that fires is one run saved.
"""
import bisect
import re

# JASS type names (common.j): a local or parameter of this name makes pjass report a syntax error on the function
# line and then one error per following declaration, none of which names the cause
TYPE_NAMES = frozenset("""
ability abilitybooleanfield abilitybooleanlevelarrayfield abilitybooleanlevelfield abilityintegerfield
abilityintegerlevelarrayfield abilityintegerlevelfield abilityrealfield abilityreallevelarrayfield
abilityreallevelfield abilitystringfield abilitystringlevelarrayfield abilitystringlevelfield agent aidifficulty
alliancetype animtype armortype attacktype blendmode boolean boolexpr buff button camerafield camerasetup code
commandbuttoneffect conditionfunc damagetype defeatcondition defensetype destructable dialog dialogevent effect
effecttype equipmentType event eventid fgamestate filterfunc fogmodifier fogstate fogstyle force frameeventtype
framehandle framepointtype gamecache gamedifficulty gameevent gamespeed gamestate gametype group handle hashtable
heroattribute igamestate image integer item itemTag itembooleanfield itemintegerfield itempool itemrealfield
itemstringfield itemtype leaderboard lightning limitop loadoutslot location mapcontrol mapdensity mapflag mapsetting
mapvisibility metakeytype minimapicon mousebuttontype movetype multiboard multiboarditem nothing originframetype
oskeytype pathingflag pathingtype placement player playercolor playerevent playergameresult playerscore
playerslotstate playerstate playerunitevent quest questitem race racepreference raritycontrol real rect regentype
region sound soundtype startlocprio string subanimtype targetflag terraindeformation texmapflags textaligntype
texttag timer timerdialog trackable trigger triggeraction triggercondition ubersplat unit unitbooleanfield
unitcategory unitevent unitintegerfield unitpool unitrealfield unitstate unitstringfield unittype
unitweaponbooleanfield unitweaponintegerfield unitweaponrealfield unitweaponstringfield version volumegroup
weapontype weathereffect widget widgetevent
""".split())
FUNCTION = re.compile(r"(?m)^[ \t]*function\s+(\w+)\s+takes\s+(.*?)\s+returns\b")
ENDFUNCTION = re.compile(r"(?m)^[ \t]*endfunction\b")
LOCAL = re.compile(r"(?m)^[ \t]*local[ \t]+(\w+)[ \t]+(?:array[ \t]+)?(\w+)")
# handle kinds that leak when the function that made them never frees them: (free call, calls that make one)
LEAKS = {"location": ("RemoveLocation", ("Location", "GetUnitLoc", "GetRectCenter", "GetSpellTargetLoc",
                                         "GetOrderPointLoc", "PolarProjectionBJ", "OffsetLocation",
                                         "GetUnitRallyPoint", "GetCameraTargetPositionLoc",
                                         "GetPlayerStartLocationLoc")),
         "group": ("DestroyGroup", ("CreateGroup",)),
         "force": ("DestroyForce", ("CreateForce", "GetPlayersAll", "GetPlayersByMapControl")),
         "rect": ("RemoveRect", ("Rect", "RectFromLoc")),
         "boolexpr": ("DestroyBoolExpr", ("Condition", "Filter", "And", "Or", "Not")),
         "effect": ("DestroyEffect", ("AddSpecialEffect", "AddSpecialEffectTarget", "AddSpecialEffectLoc",
                                      "AddSpecialEffectTargetUnitBJ", "AddSpecialEffectLocBJ"))}
ITEM_EVENTS = ("EVENT_PLAYER_UNIT_PICKUP_ITEM", "EVENT_PLAYER_UNIT_DROP_ITEM")
DAMAGE_EVENTS = ("EVENT_PLAYER_UNIT_DAMAGED", "EVENT_PLAYER_UNIT_DAMAGING", "EVENT_UNIT_DAMAGED")
INVENTORY_CHANGES = ("RemoveItem", "UnitAddItemById", "UnitAddItem", "UnitRemoveItem", "UnitAddItemToSlotById",
                     "UnitRemoveItemFromSlot")
LIFE_CHECK = re.compile(r"UNIT_STATE_LIFE|UNIT_TYPE_DEAD|\bUnitAlive\b|\bGetWidgetLife\b|\bIsUnit(?:Alive|Dead)BJ\b")
# calls that do the wrong thing on a corpse; reading one (GetUnitTypeId, its owner) is harmless, so it is left out
ON_ENUMERATED = ("UnitDamageTarget", "IssueTargetOrder", "IssuePointOrder", "IssueImmediateOrder", "KillUnit")
# natives that answer only inside the event response they belong to: after a wait the event can be another one
EVENT_NATIVES = ("GetTriggerUnit", "GetAttacker", "GetKillingUnit", "GetDyingUnit", "GetEnteringUnit", "GetLeavingUnit",
                 "GetSpellAbilityUnit", "GetSpellTargetUnit", "GetSpellTargetLoc", "GetSpellAbilityId",
                 "GetEventDamage", "GetEventDamageSource", "GetOrderedUnit", "GetIssuedOrderId", "GetLearnedSkill",
                 "GetTrainedUnit", "GetConstructingStructure", "GetSoldUnit", "GetBuyingUnit", "GetManipulatedItem",
                 "GetClickedButton", "GetClickedDialog", "GetResearched", "GetTriggerPlayer")
WAITS = ("TriggerSleepAction", "PolledWait")
# a JASS thread stops at about 300000 operations, so a loop of this many iterations needs a timer instead
OP_LIMIT = 8190
# calls that change the game state itself: inside a GetLocalPlayer() block they run on one client only
STATE_CHANGING = frozenset("""
CreateUnit CreateUnitAtLoc CreateUnitByName RemoveUnit KillUnit SetUnitX SetUnitY SetUnitPosition SetUnitPositionLoc
SetUnitOwner SetUnitState SetUnitLifePercentBJ SetUnitManaPercentBJ UnitAddAbility UnitRemoveAbility UnitAddItem
UnitAddItemById UnitRemoveItem RemoveItem CreateItem SetPlayerState AdjustPlayerStateBJ SetPlayerTechResearched
IssueImmediateOrder IssuePointOrder IssueTargetOrder IssueBuildOrderById IssueImmediateOrderById IssuePointOrderById
IssueTargetOrderById UnitDamageTarget SetHeroLevel AddHeroXP SetHeroXP SelectHeroSkill CreateDestructable
RemoveDestructable KillDestructable SetPlayerAlliance SetPlayerAllianceStateBJ TriggerExecute ConditionalTriggerExecute
EnableTrigger DisableTrigger DestroyTrigger TriggerSleepAction PolledWait SetUnitFacing PauseUnit ShowUnit
CustomVictoryBJ CustomDefeatBJ EndGameBJ SetUnitScale SetUnitVertexColor
""".split())
# random draws: each client draws its own number, so the game states drift apart
RANDOM = frozenset(("GetRandomInt", "GetRandomReal", "ChooseRandomItemEx", "ChooseRandomCreep", "GetRandomDirectionDeg",
                    "GetRandomLocInRect"))
# destroy calls whose handle is dead afterwards (KillUnit is left out: a dead unit stays a valid handle)
DESTROYED = ("RemoveUnit", "RemoveLocation", "DestroyGroup", "RemoveRect", "DestroyTrigger", "DestroyTimer",
             "RemoveItem", "DestroyEffect", "DestroyForce", "DestroyLeaderboard", "DestroyMultiboard",
             "DestroyQuest", "RemoveSaveDirectory")


def functions(text: str) -> list[tuple[str, int, str, str]]:
    """(name, line of the function header, parameter text, body) of every function in a JASS script."""
    out = []
    for m in FUNCTION.finditer(text):
        end = ENDFUNCTION.search(text, m.end())
        out.append((m[1], text.count("\n", 0, m.start()) + 1, m[2], text[m.end():end.start() if end else len(text)]))
    return out


def _calls(body: str, name: str, start: int = 0) -> int:
    """Offset of a call to `name` in `body` at or after `start`, or -1."""
    m = re.search(rf"\b{re.escape(name)}\s*\(", body[start:])
    return -1 if m is None else start + m.start()


def _line(body: str, offset: int, first_line: int) -> int:
    return first_line + body.count("\n", 0, offset)


def _hit(rule: str, line: int, function: str, message: str) -> dict:
    return {"rule": rule, "line": line, "function": function, "message": message}


def reserved_names(text: str) -> list[dict]:
    """Locals and parameters named after a JASS type: the cause of a pile of misleading pjass errors."""
    def hit(name: str, line: int, function: str, what: str) -> dict:
        return _hit("reserved_name", line, function,
                    f"{what} is named {name!r}, a JASS type name: pjass then reports a syntax error on the function "
                    f"line plus an undeclared variable for every declaration after it, and names none of them {name!r}")

    out = []
    for name, first_line, params, body in functions(text):
        for pair in params.split(","):
            words = pair.split()
            if len(words) == 2 and words[1] in TYPE_NAMES:
                out.append(hit(words[1], first_line, name, "a parameter"))
        for m in LOCAL.finditer(body):
            if m[2] in TYPE_NAMES:
                out.append(hit(m[2], _line(body, m.start(), first_line), name, "a local"))
    return out


def _leaks(name: str, first_line: int, body: str, text: str) -> list[dict]:
    out = []
    for m in LOCAL.finditer(body):
        kind, var = m[1], m[2]
        freed = LEAKS.get(kind)
        if freed is None or re.search(rf"\b{freed[0]}\s*\(\s*{re.escape(var)}\b", body):
            continue
        made = next((c for c in freed[1]
                     if re.search(rf"\b{re.escape(var)}\s*=[^\n]*\b{c}\s*\(", body)), None)
        if made:
            out.append(_hit("leak", _line(body, m.start(), first_line), name,
                            f"local {kind} {var} is created ({made}) and never freed: call {freed[0]}({var}) before "
                            "the function ends, or the handle stays for the whole game"))
    return out


def _event_after_wait(name: str, first_line: int, body: str, text: str) -> list[dict]:
    wait = min((o for o in (_calls(body, w) for w in WAITS) if o >= 0), default=-1)
    late = [n for n in EVENT_NATIVES if wait >= 0 and _calls(body, n, wait) >= 0]
    if not late:
        return []
    return [_hit("event_after_wait", _line(body, wait, first_line), name,
                 f"{late[0]}() is read after a wait: event data belongs to the trigger's current run, so read it into "
                 "a local before the wait (another event during the wait replaces it)")]


def _dead_trigger(name: str, first_line: int, body: str, text: str) -> list[dict]:
    out = []
    for m in re.finditer(r"(?m)^[ \t]*(?:local[ \t]+trigger[ \t]+(\w+)|set[ \t]+(\w+))[ \t]*=[ \t]*CreateTrigger\b",
                         body):
        var = m[1] or m[2]
        used = rf"[^)]*\b{re.escape(var)}\b"
        # anything else naming the trigger (an event, a run, another function) means it is not obviously dead
        if re.search(rf"\b(?!TriggerAddAction|TriggerAddCondition|CreateTrigger)\w+\s*\({used}", text):
            continue
        if re.search(rf"\bTriggerAdd(?:Action|Condition)\s*\({used}", body):
            out.append(_hit("dead_trigger", _line(body, m.start(), first_line), name,
                            f"trigger {var} gets an action but no event (no TriggerRegister... call names it), so it "
                            "never runs"))
    return out


def _loops(name: str, first_line: int, body: str, text: str) -> list[dict]:
    out, starts, exits = [], [], []
    for i, line in enumerate(body.splitlines()):
        word = line.strip().split("(")[0].strip()
        if word == "loop":
            starts.append(i)
            exits.append(False)
        elif word in ("exitwhen", "return") or line.strip().startswith(("exitwhen ", "return ")):
            if exits:
                exits[-1] = True
        elif word == "endloop" and starts:
            start, has_exit = starts.pop(), exits.pop()
            if not has_exit:
                out.append(_hit("endless_loop", first_line + start, name,
                                "this loop has no exitwhen and no return: the thread runs into the operation limit "
                                "(about 300000 operations) and the rest of the function never runs"))
    for m in re.finditer(r"exitwhen\s+\w+\s*>=?\s*(\d+)", body):
        if int(m[1]) > OP_LIMIT:
            out.append(_hit("op_limit", _line(body, m.start(), first_line), name,
                            f"this loop runs about {m[1]} times in one thread, which can reach the operation limit: "
                            "spread the work over a timer, or do less per iteration"))
    return out


def _after_destroy(name: str, first_line: int, body: str, text: str) -> list[dict]:
    out = []
    for m in re.finditer(r"\b(" + "|".join(DESTROYED) + r")\s*\(\s*(\w+)\s*\)", body):
        call, var = m[1], m[2]
        rest = body[m.end():]
        used = re.search(rf"\b\w+\s*\([^)\n]*\b{re.escape(var)}\b", rest)
        # only straight-line code: an else, endif or loop between the two can mean the use never follows the destroy
        if used and not re.search(r"(?m)^[ \t]*(?:else|elseif|endif|loop|endloop)\b|\bset[ \t]+"
                                  + re.escape(var) + r"[ \t]*=", rest[:used.start()]):
            out.append(_hit("after_destroy", _line(body, m.end() + used.start(), first_line), name,
                            f"{var} is used after {call}({var}): the handle is gone, so the call does nothing or "
                            "returns a default; keep another reference, or set it to null and stop using it"))
    return out


def _desync(name: str, first_line: int, body: str, text: str) -> list[dict]:
    """GetLocalPlayer() splits the clients: inside such a block only what one client sees may change, and the two
    sides must run the same number of game actions, or the players desync and drop."""
    out = []
    for m in re.finditer(r"(?m)^[ \t]*(?:if|elseif)\b[^\n]*\bGetLocalPlayer\s*\(", body):
        block = body[m.end():]
        end = re.search(r"(?m)^[ \t]*endif\b", block)
        inside = block[:end.start() if end else len(block)]
        called = {c for c in re.findall(r"\b(\w+)\s*\(", inside) if c in STATE_CHANGING or c in RANDOM}
        if called:
            worst = sorted(called, key=lambda c: (c not in STATE_CHANGING, c))[0]
            out.append(_hit("desync", _line(body, m.start(), first_line), name,
                            f"{worst}() runs inside a GetLocalPlayer() block: it changes the game state (or draws a "
                            "random number) on one client only, which desyncs a multiplayer game — keep the block to "
                            "what one player sees (sounds, text, camera, UI, selection)"))
    return out


def handlers(text: str) -> dict[str, list[tuple[str, str]]]:
    """Function -> [(event, "action" | "condition")] for every function a trigger runs on a registered event: the
    trigger variable registered with the event and given the function in the same function body."""
    out: dict[str, list[tuple[str, str]]] = {}
    # in program order: one init function makes several triggers, often reusing the same local, so a fresh
    # CreateTrigger() into a variable starts that variable's event list again
    step = re.compile(r"\bset\s+(\w+)\s*=\s*CreateTrigger\s*\("
                      r"|\bTriggerRegister\w*\s*\(\s*(\w+)\s*,[^\n]*?\b(EVENT_\w+)"
                      r"|\bTriggerAdd(Action|Condition)\s*\(\s*(\w+)\s*,\s*(?:(?:Condition|Filter)\s*\(\s*)?"
                      r"function\s+(\w+)")
    for _name, _line_no, _params, body in functions(text):
        events: dict[str, set] = {}
        for m in step.finditer(body):
            if m[1]:
                events[m[1]] = set()
            elif m[3]:
                events.setdefault(m[2], set()).add(m[3])
            else:
                for event in sorted(events.get(m[5], ())):
                    out.setdefault(m[6], []).append((event, m[4].lower()))
    return out


def _discarded_effects(name: str, first_line: int, body: str, text: str) -> list[dict]:
    """A special effect created as a statement: nothing holds it, so it plays and stays for the whole game."""
    return [_hit("leak", _line(body, m.start(), first_line), name,
                 f"{m[1]}() is called for its effect and the effect it returns is never destroyed: "
                 f"call DestroyEffect({m[1]}(...)) plays it once and frees it")
            for m in re.finditer(r"(?m)^[ \t]*call[ \t]+(AddSpecialEffect\w*)\s*\(", body)]


def _corpse_enum(name: str, first_line: int, body: str, text: str) -> list[dict]:
    """GroupEnumUnitsIn* returns dead units too; a FirstOfGroup loop that damages, orders or reads them without a
    life check works on corpses (two game runs were lost to this)."""
    enum = re.search(r"\bGroupEnumUnitsIn\w*\s*\(([^\n]*)", body)
    if not enum or "FirstOfGroup" not in body or LIFE_CHECK.search(body):
        return []
    flt = re.search(r"(?:Filter|Condition)\s*\(\s*function\s+(\w+)", enum[1])
    if flt and any(n == flt[1] and LIFE_CHECK.search(b) for n, _l, _p, b in functions(text)):
        return []
    used = next((c for c in ON_ENUMERATED if _calls(body, c) >= 0), None)
    if used is None:
        return []
    return [_hit("corpse_enum", _line(body, enum.start(), first_line), name,
                 f"this group enumeration keeps dead units, and the loop calls {used}() on them: test "
                 "GetUnitState(u, UNIT_STATE_LIFE) > 0.405 (in the loop or the filter)")]


def _hooked_rules(name: str, first_line: int, body: str, hooked: dict) -> list[dict]:
    """Rules that need to know which event a function handles, and whether it runs as an action or a condition."""
    out = []
    events = hooked.get(name, [])
    if any(e in ITEM_EVENTS for e, _how in events):
        changes = next((c for c in INVENTORY_CHANGES if _calls(body, c) >= 0), None)
        guarded = re.search(r"\bDisableTrigger\s*\(", body) or re.search(
            r"(?s)\bset\s+(\w+)\s*=\s*true\b.*\bset\s+\1\s*=\s*false\b", body)
        if changes and not guarded:
            out.append(_hit("item_reentry", first_line, name,
                            f"this item-event handler calls {changes}(), which fires the item events again before "
                            "the inventory settles (an unguarded recipe built six copies): guard it with a global "
                            "flag or DisableTrigger(GetTriggeringTrigger()) around the change"))
    if any(e in DAMAGE_EVENTS and how == "action" for e, how in events):
        out.append(_hit("damage_action", first_line, name,
                        "this damage handler runs as a trigger action, on a new thread after the damage call returned: "
                        "globals the dealer set around UnitDamageTarget are reset by then. Register it with "
                        "TriggerAddCondition(t, Condition(function ...)) returning false to run inside the call"))
    return out


RULES = (_leaks, _event_after_wait, _dead_trigger, _loops, _after_destroy, _desync, _discarded_effects, _corpse_enum)


def lint(text: str) -> list[dict]:
    """Every rule over a JASS script, by line. Warnings, not errors: each one names what to check."""
    from .validate import section_index   # validate imports this module for reserved_names

    out = reserved_names(text)
    hooked = handlers(text)
    for name, first_line, _params, body in functions(text):
        for rule in RULES:
            out += rule(name, first_line, body, text)
        out += _hooked_rules(name, first_line, body, hooked)
    marks = section_index(text)
    starts = [m[0] for m in marks]
    for hit in out:
        _, hit["section"], hit["trigger"] = marks[bisect.bisect_right(starts, hit["line"]) - 1]
    return sorted(out, key=lambda h: h["line"])
