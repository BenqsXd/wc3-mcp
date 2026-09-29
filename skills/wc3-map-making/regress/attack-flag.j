// UnitDamageTarget(attack=true) must not set BlzGetEventIsAttack (game-behaviour.md, Combat).
// The handler leaves its verdict in the target's user data: 1 = flag true, 2 = flag false.
local unit a = CreateUnit(Player(0), 'hfoo', 0, 0, 0)
local unit t = CreateUnit(Player(PLAYER_NEUTRAL_PASSIVE), 'hfoo', 300, 0, 0)
local trigger g = CreateTrigger()
call PauseUnit(a, true)
call TriggerRegisterUnitEvent(g, t, EVENT_UNIT_DAMAGED)
call TriggerAddAction(g, function RegressFlagHandler)
call UnitDamageTarget(a, t, 1.0, true, false, ATTACK_TYPE_NORMAL, DAMAGE_TYPE_NORMAL, WEAPON_TYPE_WHOKNOWS)
call TriggerSleepAction(0.5)
call ProbeExpect("damage event fired", GetUnitUserData(t) != 0)
call ProbeExpect("scripted attack=true is not an attack in the event", GetUnitUserData(t) == 2)
