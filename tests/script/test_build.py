import pytest

from corpus import HAVE_INSTALL, _storage, open_sample, sample_map_ids
from wc3mcp.formats import wct, wtg
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.script import build

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs TriggerData from the install")


@pytest.fixture(scope="module")
def td():
    return Catalog(_storage(), balance=None).trigger_data


def test_type_defaults(td):
    assert td.type_defaults["group"] == "CreateGroup()" and td.type_defaults["boolean"] == "false"


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_splice_reproduces_editor_scripts(map_id, td):
    arc = open_sample(map_id)
    script, data = arc.read("war3map.j"), arc.read("war3map.wtg")
    if script is None or data is None:
        pytest.skip("not a JASS map with triggers")
    original = script.decode("utf-8")
    assert build.splice(original, wtg.parse(data, td.arg_count), wct.parse(arc.read("war3map.wct")), td) == original


def test_runs_on_init_follows_the_editor():
    # the World Editor honours the "run on map initialization" flag only for custom text triggers; a GUI trigger runs
    # at initialization through its Map Initialization event, whatever the flag says
    event = wtg.ECA(build.EVENT, "MapInitializationEvent")
    assert build.runs_on_init(wtg.Trigger(wtg.TRIGGER, "Text", custom_text=1, run_on_init=1))
    assert not build.runs_on_init(wtg.Trigger(wtg.TRIGGER, "Gui", run_on_init=1))
    assert build.runs_on_init(wtg.Trigger(wtg.TRIGGER, "Gui", ecas=[event]))
    assert not build.runs_on_init(wtg.Trigger(wtg.TRIGGER, "Off", ecas=[event], initially_off=1))


def test_splice_rejects_foreign_scripts(td):
    with pytest.raises(ValueError):
        build.splice("function main takes nothing returns nothing\r\nendfunction\r\n", wtg.TriggerFile(),
                     wct.CustomText(), td)
