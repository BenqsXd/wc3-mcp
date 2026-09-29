import pytest

from wc3mcp import config
from wc3mcp.formats import desync

SEP = "=" * 71


def _log(tech_value: str, game_sum: int) -> str:
    return "\n".join([
        SEP, "[Desync - 1918987876 - Turn(00000012) = 77]", "\t#0#: 0x0000004D",
        SEP, f"[Desync - 1735876978 - Turn(00000012) = {game_sum}]",
        "\t#1886287213#", "\t\t#1886157171#", "\t\t\t#1952801640#",
        f"\t\t\t\t#1952801641#: {tech_value}", "\t\t\t\t#1952801643#: 0x00000000",
        "\t#1886287236#: 0x16FFE3B1",
        SEP, "[Desync - 1668641652 - Turn(00000012) = 5]", "\t#0#: 0x00000005",
        SEP, "[Desync - 1668641652 - Turn(00000012) = 6]", "\t#0#: 0x00000006", ""])


def test_log_sections_are_named_by_fourcc_and_nest_by_tabs():
    f = desync.parse(_log("0x68727474", 100))
    assert f.kind == "log" and [(s.id, s.occurrence, s.turn) for s in f.sections] == [
        ("rand", 0, 12), ("gwar", 0, 12), ("cust", 0, 12), ("cust", 1, 12)]
    gwar = f.sections[1]
    assert gwar.checksum == 100 and gwar.lines[3] == ("pnum/plys/tech/teci", "0x68727474 (hrtt)")
    assert gwar.lines[-1] == ("1886287236", "0x16FFE3B1")   # 'pnu\x84' is no text: the number stays


def test_compare_finds_the_first_differing_section_and_value():
    a, b, c = (desync.parse(_log(v, s)) for v, s in (("0x68727474", 100), ("0x68727475", 101), ("0x68727474", 100)))
    diffs = desync.compare([a, b, c])
    assert [d["section"] for d in diffs] == ["gwar"]
    first = diffs[0]["first_difference"]
    assert diffs[0]["checksums"] == ["00000064", "00000065", "00000064"] and first["line"] == 3
    assert [v["value"] for v in first["values"]] == ["0x68727474 (hrtt)", "0x68727475 (hrtu)", "0x68727474 (hrtt)"]
    assert desync.compare([a, c]) == []


REPORT = """<Exception.Summary:>
Network desync on turn 12 in game W3-TEST
<:Exception.Summary>
War3 build 7000
War3 unit checksum 0000abcd
War3 game checksum 00000064
<Map> <GameDocumentRoot>/Maps/Test.w3x
<PlayerCount> 2
"""


def test_report_checksums_and_summary():
    f = desync.parse(REPORT)
    assert f.kind == "report" and f.info["turn"] == 12 and f.info["game"] == "W3-TEST" and f.info["PlayerCount"] == "2"
    assert [(s.id, s.checksum) for s in f.sections] == [("unit", 0xABCD), ("game", 100)]
    other = desync.parse(REPORT.replace("0000abcd", "0000abce"))
    assert [d["section"] for d in desync.compare([f, other])] == ["unit"]


def _local_logs():
    root = config.documents()
    return sorted(root.glob("Logs/*_Desync.log")) + sorted(root.glob("Errors/*/Desync.txt")) if root.is_dir() else []


@pytest.mark.skipif(not _local_logs(), reason="no local desync files")
def test_local_desync_files_parse():
    for path in _local_logs():
        f = desync.parse(path.read_text("utf-8", "replace"))
        assert f.sections, path.name
        if f.kind == "log":
            assert any(s.id == "gwar" for s in f.sections) and desync.compare([f, f]) == []


def test_desync_read_tool_compares_logs_and_reports_apart(tmp_path):
    from wc3mcp.ops.replay import desync_read

    paths = []
    for i, text in enumerate([_log("0x68727474", 100), _log("0x68727475", 101), REPORT]):
        paths.append(tmp_path / f"{i}.log")
        paths[-1].write_text(text)
    out = desync_read([str(p) for p in paths])
    assert [f["kind"] for f in out["files"]] == ["log", "log", "report"]
    assert out["files"][0]["sections"][1] == {"section": "gwar", "occurrence": 0, "checksums": {"12": "00000064"},
                                              "lines": 6}
    (diff,) = out["differences"]
    assert diff["kind"] == "log" and diff["files"] == [0, 1] and diff["sections"][0]["section"] == "gwar"
    assert "note" in desync_read([str(paths[0])])
