import functools

import pytest

from corpus import HAVE_INSTALL, _storage
from wc3mcp.formats import wai, wtg
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.script import ai as aigen

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@functools.cache
def td():
    return aigen.ai_trigger_data(Catalog(_storage()))


def game_pairs() -> list[str]:
    if not HAVE_INSTALL:
        return []
    names = _storage().list("")
    ai = {n.lower()[:-3] for n in names if n.lower().endswith(".ai")}
    return sorted(n for n in names if n.lower().endswith(".wai") and n.lower()[:-4] in ai)


@pytest.mark.parametrize("name", game_pairs())
def test_export_matches_the_games_exported_scripts(name):
    """The game's .ai files were exported by the AI Editor from these .wai files; the current editor writes the same
    text without the Date line (and the u05/u08 files carry an extra revision comment)."""
    s = _storage()
    want = s.read(name[:-4] + ".ai").decode("utf-8").split("\r\n")
    want = "\r\n".join(line for line in want if not line.startswith(("//   Date: ", "//\t Reforged revision")))
    assert aigen.export(wai.parse(s.read(name), td().arg_count), td()) == want


def lines(ai: wai.AIData) -> str:
    return aigen.export(ai, td()).replace("\r\n", "\n")


def base(**changes) -> wai.AIData:
    ai = wai.AIData(name="Rules", race=2, options=0x2001, workers=[b"opeo", b"opeo", b"ogre", b"ogre"],
                    groups=[wai.AttackGroup(0, "b group"), wai.AttackGroup(1, "A group", [wai.GroupUnit(b"ogru", 2, 4)])],
                    waves=[wai.Wave(1, 0), wai.Wave(0, 30)], repeat_waves=1, minimum_group=1)
    for key, value in changes.items():
        setattr(ai, key, value)
    return ai


def test_rules_verified_with_the_editor():
    gold = wai.Condition("", "OperatorCompareInteger",
                         [wtg.Param(2, "GetGold", wtg.Call(3, "GetGold", [])), wtg.Param(0, "OperatorGreater"), wtg.Param(3, "300")])
    text = lines(base(
        heroes=[b"Obla", b"\0\0\0\0", b"Ofar"], hero_orders=[0, 50, 0, 0, 50, 0],
        build=[wai.BuildPriority(0, b"otrb", 0), wai.BuildPriority(0, b"otrb", -3), wai.BuildPriority(0, b"otrb", -1),
               wai.BuildPriority(2, b"XEIA", -1, wai.CUSTOM_CONDITION, gold),
               wai.BuildPriority(2, b"XEIA", -1, wai.CUSTOM_CONDITION, gold)],
        targets=[wai.TargetPriority(6), wai.TargetPriority(5, 3, 7, 1)]))
    # hero orders are permutations of the three hero slots; empty slots drop out but keep their positions
    assert ("    if (roll <= 50) then\n        call SetHero( 1, 'Obla' )\n        call SetHero( 2, 'Ofar' )\n"
            "    else\n        call SetHero( 1, 'Ofar' )\n        call SetHero( 2, 'Obla' )\n    endif\n") in text
    # SetHero covers the leading hero slots that are set, listing every hero
    assert "    elseif (order == 2)" not in text and "        elseif (heroid == 'Ofar') then" in text
    # build counts: per id for any town, per id and town otherwise; identical custom conditions share a block
    assert ("    call SetBuildAll( BUILD_UNIT, 1, 'otrb', 0 )\n    call SetBuildAll( BUILD_UNIT, 1, 'otrb', mine + 0 )\n"
            "    call SetBuildAll( BUILD_UNIT, 3, 'otrb', -1 )\n    if (( GetGold(  ) > 300 )) then\n"
            "        call BuildExpansion( 'ogre', 'ogre' )\n        call BuildExpansion( 'ogre', 'ogre' )\n    endif\n") in text
    assert "        call PurchaseZeppelin(  )\n        return\n" in text and "GetCreepCamp( 3, 7, true )" in text
    # groups are numbered by name (ordinal order), waves repeat from waves - repeat + 1, delays per wave
    assert "    // Attack Group #1: A group\n    if (groupID == 1) then\n        call AddAttackUnit( 2,   4,   'ogru' )" in text
    assert "    if (attackWave == 1) then\n        call PrepareAttackGroup( 1 )\n    elseif (attackWave == 2) then\n" \
           "        call PrepareAttackGroup( 2 )" in text
    assert "    if (inWave == 2) then\n        call Sleep( 30 )\n    endif\n" in text
    assert "        set attackWave = 2\n" in text and 'call SetPlayerName( ai_player, "Rules" )' in text
    assert "    // Attack Group: A group\n    set count = GetUnitCountDone( 'ogru' )\n    if (count < 2) then" in text


def test_wrong_presets_and_empty_groups_as_the_editor_writes_them():
    wrong = wai.Condition("W", "OperatorCompareInteger",
                          [wtg.Param(3, "1"), wtg.Param(0, "OperatorEqualENE"), wtg.Param(3, "2")])
    text = lines(base(conditions=[wai.NamedCondition(0, wrong)], minimum_group=0, repeat_waves=0))
    assert "    set gCond_W = ( 1 Error 2 )\n" in text
    assert "    // - No units in this attack group.  Never attack\n    return false\nendfunction" in text
    assert "if (attackWave > 2) then\n        set attackWave" not in text
