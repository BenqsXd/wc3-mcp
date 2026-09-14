import pytest

from corpus import open_sample, sample_map_ids
from wc3mcp.formats import imp
from wc3mcp.formats.binary import FormatError


def test_build_serialize_parse():
    lst = imp.ImportList(1, [imp.ImportEntry(29, "war3mapImported/a.blp"), imp.ImportEntry(13, "conversation.json")])
    data = imp.serialize(lst)
    assert data == b"\x01\x00\x00\x00\x02\x00\x00\x00\x1dwar3mapImported/a.blp\x00\x0dconversation.json\x00"
    assert imp.parse(data) == lst


def test_rejects_bad_input():
    with pytest.raises(FormatError):
        imp.parse(b"\x01\x00\x00\x00\xff\xff\x00\x00")  # count larger than the data
    with pytest.raises(FormatError):
        imp.parse(b"\x01\x00\x00\x00\x01\x00\x00\x00\x1dno-terminator")
    with pytest.raises(FormatError):
        imp.parse(b"\x07\x00\x00\x00\x00\x00\x00\x00")  # unknown version


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_roundtrip(map_id):
    data = open_sample(map_id).read("war3map.imp")
    if data is None:
        pytest.skip("map has no import list")
    lst = imp.parse(data)
    assert lst.trailing == b"" and imp.serialize(lst) == data
