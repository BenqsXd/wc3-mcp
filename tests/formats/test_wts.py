import pytest

from corpus import open_sample, sample_map_ids
from wc3mcp.formats.wts import TriggerStrings

SAMPLE = ("\N{ZERO WIDTH NO-BREAK SPACE}STRING 1\r\n{\r\nHammerfall\r\n}\r\n\r\n"
          "STRING 2\r\n// Units: hfoo\r\n{\r\nline one\r\nline two\r\n}\r\n\r\n").encode("utf-8")


def test_lossless_parse_get_resolve():
    ts = TriggerStrings.parse(SAMPLE)
    assert ts.serialize() == SAMPLE
    assert ts.get(1) == "Hammerfall" and ts.get(2) == "line one\nline two" and ts.get(3) is None
    assert ts.resolve("TRIGSTR_002") == "line one\nline two"
    assert ts.resolve("plain") == "plain" and ts.resolve("TRIGSTR_9") == "TRIGSTR_9"


def test_set_add_remove_keep_file_style():
    ts = TriggerStrings.parse(SAMPLE)
    ts.set(1, "New Name")
    assert ts.add("Added\ntext") == 3
    assert ts.remove(2) == 1
    assert ts.serialize() == ("\N{ZERO WIDTH NO-BREAK SPACE}STRING 1\r\n{\r\nNew Name\r\n}\r\n"
                              "\r\nSTRING 3\r\n{\r\nAdded\r\ntext\r\n}\r\n\r\n").encode("utf-8")


def test_double_encoded_bom_and_lf_files():
    data = "\xef\xbb\xbfSTRING 0\n{\nPlayer 1\n}\n".encode("utf-8")  # double-encoded BOM
    ts = TriggerStrings.parse(data)
    assert ts.get(0) == "Player 1" and ts.newline == "\n" and ts.serialize() == data
    ts.add("Force 1")
    assert ts.serialize().endswith(b"\nSTRING 1\n{\nForce 1\n}\n")


def test_empty_file_gets_bom_on_first_add():
    ts = TriggerStrings.parse(b"")
    assert ts.add("Hello") == 1
    assert ts.serialize() == "\N{ZERO WIDTH NO-BREAK SPACE}STRING 1\r\n{\r\nHello\r\n}\r\n".encode("utf-8")


def test_set_missing_id_adds_it_and_empty_text():
    ts = TriggerStrings.parse(SAMPLE)
    ts.set(10, "")
    assert ts.get(10) == ""
    assert TriggerStrings.parse(ts.serialize()).get(10) == ""


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_roundtrip(map_id):
    arc = open_sample(map_id)
    names = [n for n in arc.list() if n.lower().endswith(".wts")]
    assert names
    for name in names:
        data = arc.read(name)
        ts = TriggerStrings.parse(data)
        assert ts.serialize() == data, name
        assert all(ts.get(e.id) is not None for e in ts.entries)
