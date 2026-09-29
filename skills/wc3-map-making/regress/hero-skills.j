// A new hero set to level 10 holds 10 skill points; a hero ability made unavailable cannot be learned
// (game-behaviour.md, Heroes). Paladin AHhb (Holy Light) is a stock level-1 basic.
local unit h = CreateUnit(Player(0), 'Hpal', 0, 0, 0)
call SetHeroLevel(h, 10, false)
call ProbeExpect("level 10 hero has 10 unspent points", GetHeroSkillPoints(h) == 10)
call SetPlayerAbilityAvailable(Player(0), 'AHhb', false)
call SelectHeroSkill(h, 'AHhb')
call ProbeExpect("unavailable ability is not learned", GetUnitAbilityLevel(h, 'AHhb') == 0)
call ProbeExpect("and costs no point", GetHeroSkillPoints(h) == 10)
call SetPlayerAbilityAvailable(Player(0), 'AHhb', true)
call SelectHeroSkill(h, 'AHhb')
call ProbeExpect("available again it is learned", GetUnitAbilityLevel(h, 'AHhb') == 1)
call SetPlayerAbilityAvailable(Player(0), 'AHhb', true)
