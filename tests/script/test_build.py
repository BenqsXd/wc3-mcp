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


def _without_triggers(script: str) -> str:
    """What the World Editor may write for a map with no triggers: no Triggers banner, no InitCustomTriggers."""
    from wc3mcp.script.build import BAR, banner

    crlf = lambda s: s.replace("\n", "\r\n")  # noqa: E731
    script = script.replace(crlf(banner("Triggers") + "\n"), "")
    start = script.find(crlf(f"{BAR}\nfunction InitCustomTriggers takes nothing returns nothing\n"))
    end = script.find("\r\nendfunction\r\n\r\n", start) + len("\r\nendfunction\r\n\r\n")
    return script[:start] + script[end:] if start >= 0 else script


def test_splice_puts_the_trigger_section_back(tmp_path):
    from pathlib import Path

    from corpus import _storage
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops.newmap import new_map
    from wc3mcp.ops.script import script_build, script_validate
    from wc3mcp.ops.triggers import triggers_edit

    c = Catalog(_storage(), balance="Custom_V1")
    p = new_map(str(tmp_path / "Z.w3x"), c, width=64, height=64, players=2)
    triggers_edit(p, c, [{"op": "delete", "what": "trigger", "name": "Melee Initialization"}])
    script_build(p, c)          # the script the tools write for a map with no triggers: an empty Triggers section
    fixture = Path(__file__).parent / "data" / "no_triggers.j"
    bare = fixture.read_bytes() if fixture.exists() else _without_triggers(
        p.read("war3map.j").decode("utf-8")).encode("utf-8")
    p.write("war3map.j", bare)
    script_build(p, c)
    triggers_edit(p, c, [{"op": "trigger", "name": "Hello", "script": 'call BJDebugMsg("hi")', "run_on_init": True}],
                  validate=True)
    text = p.read("war3map.j").decode("utf-8")
    assert "//*  Triggers" in text and "call InitTrig_Hello(  )" in text
    assert script_validate(p, c)["ok"]
