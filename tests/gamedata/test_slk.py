from corpus import INSTALL, needs_install
from wc3mcp.gamedata.slk import parse_slk

SAMPLE = (b'ID;PWXL;N;E\r\nB;X3;Y3;D0\r\nC;X1;Y1;K"unitID"\r\nC;X2;K"HP"\r\nC;X3;K"name"\r\n'
          b'C;X1;Y2;K"hfoo"\r\nC;X2;K420\r\nC;X3;K"Foot;man"\r\nC;X1;Y3;K"hkni"\r\nC;X3;K"Knight"\r\nE\r\n')


def test_parse_slk_rows_and_quoting():
    t = parse_slk(SAMPLE)
    assert t.columns == ["unitID", "HP", "name"]
    assert t.rows["hfoo"] == {"unitID": "hfoo", "HP": "420", "name": "Foot;man"}
    assert t.rows["hkni"] == {"unitID": "hkni", "name": "Knight"}


def test_empty_input():
    t = parse_slk(b"ID;PWXL\r\nE\r\n")
    assert t.columns == [] and t.rows == {}


@needs_install
def test_real_ability_data():
    from wc3mcp.casc.storage import open_storage

    t = parse_slk(open_storage(INSTALL).read("War3.w3mod:Units/AbilityData.slk"))
    assert t.columns[0] == "alias"
    assert [t.rows["AHbz"][f"DataA{i}"] for i in (1, 2, 3)] == ["6", "8", "10"]
