from wc3mcp.script.lint import lint, reserved_names

TRAPS = """
function RR_Ab takes integer code returns nothing
    local group g = CreateGroup()
    local location where = GetUnitLoc(udg_Hero)
    local integer i = 0
    call GroupEnumUnitsInRange(g, 0, 0, 500, null)
    loop
        set i = i + 1
        exitwhen i > 20000
    endloop
    loop
        call TriggerSleepAction(1)
    endloop
endfunction

function RR_Late takes nothing returns nothing
    local trigger t = CreateTrigger()
    local unit u = GetTriggerUnit()
    call TriggerAddAction(t, function RR_Ab)
    call TriggerSleepAction(2.0)
    call KillUnit(GetTriggerUnit())
    call RemoveUnit(u)
    call SetUnitX(u, 0)
endfunction
"""

CLEAN = """
function RR_Ok takes nothing returns nothing
    local group g = CreateGroup()
    local unit u = GetTriggerUnit()
    local trigger t = CreateTrigger()
    call TriggerRegisterAnyUnitEventBJ(t, EVENT_PLAYER_UNIT_DEATH)
    call TriggerAddAction(t, function RR_Ok)
    call GroupEnumUnitsInRange(g, 0, 0, 500, null)
    call DestroyGroup(g)
    call SetUnitX(u, 0)
    call RemoveUnit(u)
    set u = null
    set g = null
endfunction
"""


def test_every_rule_fires_once_on_a_script_full_of_traps():
    rules = {}
    for hit in lint(TRAPS):
        rules.setdefault(hit["rule"], []).append(hit)
        assert hit["function"] in ("RR_Ab", "RR_Late") and hit["line"] > 1
    assert set(rules) == {"reserved_name", "leak", "op_limit", "endless_loop", "dead_trigger", "event_after_wait",
                          "after_destroy"}
    assert "'code'" in rules["reserved_name"][0]["message"] and rules["reserved_name"][0]["line"] == 2
    assert {h["message"].split()[1] for h in rules["leak"]} == {"group", "location"}
    assert "20000" in rules["op_limit"][0]["message"] and "exitwhen" in rules["endless_loop"][0]["message"]
    assert "GetTriggerUnit()" in rules["event_after_wait"][0]["message"]
    assert "RemoveUnit(u)" in rules["after_destroy"][0]["message"]


def test_a_script_that_frees_its_handles_and_registers_its_trigger_is_quiet():
    assert lint(CLEAN) == []
    assert reserved_names(CLEAN) == []


def test_a_destroy_in_one_branch_is_not_a_use_after_destroy():
    """The use is in the other branch of the if, so the destroy never precedes it at runtime."""
    script = """
function RR_Branch takes nothing returns nothing
    local unit u = GetTriggerUnit()
    if GetUnitState(u, UNIT_STATE_LIFE) < 1 then
        call RemoveUnit(u)
    else
        call SetUnitX(u, 0)
    endif
    set u = null
endfunction
"""
    assert [h["rule"] for h in lint(script)] == []


def test_findings_name_the_trigger_of_an_editor_generated_script():
    script = ("//" + "=" * 75 + "\n// Trigger: Spawns\n//" + "=" * 75 + "\n"
              "function Trig_Spawns_Actions takes nothing returns nothing\n"
              "    local group g = CreateGroup()\n    call GroupClear(g)\nendfunction\n")
    [hit] = lint(script)
    assert hit["rule"] == "leak" and hit["trigger"] == "Spawns"


def test_a_local_player_block_that_changes_the_game_is_a_desync():
    script = """
function RR_Show takes nothing returns nothing
    if GetLocalPlayer() == Player(0) then
        call ClearTextMessages()
        call SetCameraPosition(0, 0)
        call BlzSetAbilityResearchTooltip('A000', "text", 1)
    endif
    if GetLocalPlayer() == Player(0) then
        call CreateUnit(Player(0), 'hfoo', 0, 0, 270)
    endif
    if GetLocalPlayer() == Player(1) then
        set udg_n = GetRandomInt(1, 5)
    endif
endfunction
"""
    hits = [h for h in lint(script) if h["rule"] == "desync"]
    assert len(hits) == 2                                    # the first block only changes what one player sees
    assert hits[0]["message"].startswith("CreateUnit() runs inside a GetLocalPlayer() block")
    assert hits[1]["message"].startswith("GetRandomInt() runs inside a GetLocalPlayer() block")


HANDLERS = """
function Fx takes nothing returns nothing
    local effect e = AddSpecialEffect("x.mdl", 0, 0)
    call AddSpecialEffectTarget("y.mdl", udg_Hero, "origin")
    call DestroyEffect(AddSpecialEffect("z.mdl", 0, 0))
endfunction

function Burn takes nothing returns nothing
    local group g = CreateGroup()
    local unit u
    call GroupEnumUnitsInRange(g, 0, 0, 500, null)
    loop
        set u = FirstOfGroup(g)
        exitwhen u == null
        call GroupRemoveUnit(g, u)
        call UnitDamageTarget(udg_Hero, u, 50, true, false, ATTACK_TYPE_NORMAL, DAMAGE_TYPE_MAGIC, null)
    endloop
    call DestroyGroup(g)
endfunction

function Combine takes nothing returns nothing
    call RemoveItem(GetManipulatedItem())
    call UnitAddItemById(GetTriggerUnit(), 'ratc')
endfunction

function OnHit takes nothing returns nothing
    call BlzSetEventDamage(0)
endfunction

function InitTrig_Items takes nothing returns nothing
    set gg_trg_Items = CreateTrigger(  )
    call TriggerRegisterAnyUnitEventBJ( gg_trg_Items, EVENT_PLAYER_UNIT_PICKUP_ITEM )
    call TriggerAddAction( gg_trg_Items, function Combine )
    set gg_trg_Hits = CreateTrigger(  )
    call TriggerRegisterAnyUnitEventBJ( gg_trg_Hits, EVENT_PLAYER_UNIT_DAMAGED )
    call TriggerAddAction( gg_trg_Hits, function OnHit )
endfunction
"""


def test_the_new_rules_fire_once_each():
    rules = [h["rule"] for h in lint(HANDLERS)]
    assert rules.count("leak") == 2                       # the local effect and the discarded one
    assert rules.count("corpse_enum") == 1 and rules.count("item_reentry") == 1 and rules.count("damage_action") == 1


def test_guarded_code_is_quiet():
    guarded = (HANDLERS
               .replace("        call GroupRemoveUnit(g, u)\n",
                        "        call GroupRemoveUnit(g, u)\n        if GetUnitState(u, UNIT_STATE_LIFE) > 0.405 then\n")
               .replace("DAMAGE_TYPE_MAGIC, null)\n", "DAMAGE_TYPE_MAGIC, null)\n        endif\n")
               .replace("function Combine takes nothing returns nothing\n",
                        "function Combine takes nothing returns nothing\n    call DisableTrigger(GetTriggeringTrigger())\n")
               .replace("call TriggerAddAction( gg_trg_Hits, function OnHit )",
                        "call TriggerAddCondition( gg_trg_Hits, Condition(function OnHit) )"))
    rules = [h["rule"] for h in lint(guarded)]
    assert "corpse_enum" not in rules and "item_reentry" not in rules and "damage_action" not in rules
