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
