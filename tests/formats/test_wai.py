import functools

import pytest

from corpus import HAVE_INSTALL, _storage
from wc3mcp.formats import wai
from wc3mcp.formats.binary import FormatError
from wc3mcp.gamedata.triggerdata import TriggerData

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@functools.cache
def arg_count():
    s = _storage()
    ai_functions = s.read("War3.w3mod:UI/AIEditorData.txt").replace(b"[AIFunctions]", b"[TriggerCalls]")
    return TriggerData.parse(s.read("War3.w3mod:UI/TriggerData.txt") + b"\r\n" + ai_functions).arg_count


def samples() -> list[str]:
    return sorted(n for n in _storage().list("") if n.lower().endswith(".wai")) if HAVE_INSTALL else []


@pytest.mark.parametrize("name", samples())
def test_game_ai_files_round_trip(name):
    data = _storage().read(name)
    assert wai.serialize(wai.parse(data, arg_count())) == data


def test_decoded_values():
    grunt = wai.parse(_storage().read("War3.w3mod:AI Scripts/GruntMaster.wai"), arg_count())
    assert (grunt.name, grunt.race, grunt.workers) == ("Grunt Master", 2, [b"opeo", b"opeo", b"ogre", b"ogre"])
    assert grunt.conditions[0].condition.name == "Barracks 2" and grunt.conditions[0].condition.function == "GetBooleanAnd"
    assert grunt.groups[1].name == "Minimum" and grunt.minimum_group == 1 and grunt.object_data is None
    assert grunt.test_map == "Maps\\(4)LostTemple.w3m" and [p.ai for p in grunt.players] == [3, 12, 0]
    navy = wai.parse(_storage().read("War3.w3mod:Scripts/reforged_u05_navy.wai"), arg_count())
    assert navy.object_data.path.endswith("u05Data.w3o") and navy.object_data.tables[0].original[0].base_id == b"hmil"
    assert isinstance(navy.targets[5], wai.TargetPriority) and (navy.targets[5].creep_min, navy.targets[5].creep_max) == (0, 9)


def test_new_ai_round_trips_and_bad_input():
    ai = wai.AIData(name="Tester", race=1, workers=[b"hpea", b"hpea", b"htow", b"htow"],
                    build=[wai.BuildPriority(0, b"hbar", -1)], harvest=[wai.HarvestPriority(0, 0, 5)],
                    targets=[wai.TargetPriority(5, 0, 9, 1)],
                    groups=[wai.AttackGroup(0, "All", [wai.GroupUnit(b"hfoo", 4, 6)])], waves=[wai.Wave(0, 30)])
    assert wai.parse(wai.serialize(ai), arg_count()) == ai
    with pytest.raises(FormatError):
        wai.parse(b"\x01\x00\x00\x00", arg_count())
