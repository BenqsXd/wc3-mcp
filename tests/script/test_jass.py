import re

import pytest

from corpus import HAVE_INSTALL, _storage, open_sample, sample_map_ids
from wc3mcp.formats import wct, wtg
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.script.jass import BAR, JassGen

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs TriggerData from the install")


@pytest.fixture(scope="module")
def td():
    return Catalog(_storage(), balance=None).trigger_data


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_trigger_sections_match_the_editor(map_id, td):
    arc = open_sample(map_id)
    script, data = arc.read("war3map.j"), arc.read("war3map.wtg")
    if script is None or data is None:
        pytest.skip("not a JASS map with triggers")
    tf, ct = wtg.parse(data, td.arg_count), wct.parse(arc.read("war3map.wct"))
    text = script.decode("utf-8").replace("\r\n", "\n")
    expected = [p for p in re.split(r"(?m)^(?=" + re.escape(BAR) + r"\n(?:// Trigger: |function InitCustomTriggers))", text)
                if p.startswith(BAR + "\n// Trigger: ")]
    gen = JassGen(td, {v.name: v for v in tf.variables})
    triggers = [e for e in tf.elements if isinstance(e, wtg.Trigger) and e.kind == wtg.TRIGGER]
    got = [gen.section(t, s) for t, s in zip(triggers, ct.texts) if t.enabled and not t.is_comment]
    assert got == expected
