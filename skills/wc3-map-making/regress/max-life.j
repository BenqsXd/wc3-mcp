// BlzSetUnitMaxHP changes max life; SetUnitState(UNIT_STATE_MAX_LIFE) does not (game-behaviour.md, Timers, stats).
local unit a = CreateUnit(Player(0), 'hfoo', 0, 0, 0)
local unit b = CreateUnit(Player(0), 'hfoo', 100, 0, 0)
local integer base = BlzGetUnitMaxHP(a)
call BlzSetUnitMaxHP(a, base + 100)
call SetUnitState(b, UNIT_STATE_MAX_LIFE, base + 100)
call TriggerSleepAction(0.2)
call ProbeExpect("BlzSetUnitMaxHP raises max life", BlzGetUnitMaxHP(a) == base + 100)
call ProbeExpect("SetUnitState MAX_LIFE still does not", BlzGetUnitMaxHP(b) == base)
