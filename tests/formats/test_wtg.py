import pytest

from corpus import HAVE_INSTALL, _storage, open_sample, sample_map_ids
from wc3mcp.formats import wct, wtg
from wc3mcp.formats.binary import FormatError
from wc3mcp.formats.wtg import ECA, Call, Category, Param, Trigger, TriggerFile, Variable, VariableElement

ARGS = {(0, "MapInitializationEvent"): 0, (1, "OperatorCompareBoolean"): 3, (2, "TriggerSleepAction"): 1,
        (2, "IfThenElseMultiple"): 0, (3, "GetBooleanAnd"): 2}


def fake_count(kind, name):
    return ARGS.get((kind, name))


def sample_file() -> TriggerFile:
    condition = ECA(1, "OperatorCompareBoolean", params=[
        Param(1, "flag", index=Param(3, "1")), Param(0, "OperatorEqualENE"),
        Param(2, "GetBooleanAnd", Call(3, "GetBooleanAnd", [Param(3, "true"), Param(-1, "")]))])
    block = ECA(2, "IfThenElseMultiple", children=[
        condition, ECA(2, "TriggerSleepAction", enabled=0, params=[Param(3, "1")], group=1)])
    start = Trigger(8, "Start", "desc", id=0x03000000, parent=0x02000000,
                    ecas=[ECA(0, "MapInitializationEvent"), ECA(2, "TriggerSleepAction", params=[Param(3, "2")]), block])
    return TriggerFile(
        counters=[(1, []), (0, []), (2, [1]), (1, []), (1, []), (0, []), (1, []), (0, [])],
        variables=[Variable("flag", "boolean", is_array=1, array_size=4, id=0x06000000, parent=0x02000000)],
        elements=[Category(1, 0, "map.w3x"), Category(4, 0x02000000, "Init", expanded=1, parent=0), start,
                  Trigger(16, "note", "a comment", is_comment=1, id=0x04000000, parent=0x02000000),
                  VariableElement(0x06000000, "flag", 0x02000000)])


def test_constructed_roundtrip():
    tf = sample_file()
    assert wtg.parse(wtg.serialize(tf), fake_count) == tf
    ct = wct.CustomText(comment="map notes", header="// header",
                        texts=[None, "function X takes nothing returns nothing\nendfunction"])
    assert wct.parse(wct.serialize(ct)) == ct


def test_rejects_unsupported_input():
    with pytest.raises(FormatError):
        wtg.parse(b"WTG!" + (7).to_bytes(4, "little") + bytes(8), fake_count)
    with pytest.raises(FormatError):
        wtg.parse(wtg.serialize(sample_file()), lambda kind, name: None)
    with pytest.raises(FormatError):
        wct.parse((1).to_bytes(4, "little") + bytes(8))


@pytest.fixture(scope="module")
def trigger_data():
    from wc3mcp.gamedata.catalog import Catalog

    return Catalog(_storage(), balance=None).trigger_data


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs TriggerData from the install")
@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_roundtrip_is_byte_exact(map_id, trigger_data):
    arc = open_sample(map_id)
    data = arc.read("war3map.wtg")
    if data is None:
        pytest.skip("map has no trigger data")
    tf = wtg.parse(data, trigger_data.arg_count)
    assert tf.trailing == b"" and wtg.serialize(tf) == data
    text = arc.read("war3map.wct")
    ct = wct.parse(text)
    assert wct.serialize(ct) == text
    assert len(ct.texts) == sum(1 for e in tf.elements if isinstance(e, Trigger) and e.kind == wtg.TRIGGER)
