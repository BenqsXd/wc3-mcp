import pytest

from wc3mcp.script import lua

NATIVES = lua.Types("native I2S takes integer i returns string\nnative Print takes string s returns nothing\n")


def test_transpile_types_expressions_and_passes_raw_lines():
    jass = ("globals\n    real r = 1\n    string array names\n    string label\nendglobals\n"
            "function F takes integer a returns string\n    local string s = null\n    set r = 2\n"
            "    if ( ( a != 0 ) ) then\n        return s + I2S(a / 2)\n    elseif a == 'hfoo' then\n"
            "        call Print(null)\n    endif\n\x01    print('raw')\n    loop\n        exitwhen a > $10\n"
            "    endloop\n    return null\nendfunction\n")
    assert lua.transpile(jass, NATIVES) == (
        'r = 1.0\r\nnames = __jarray("")\r\nlabel = ""\r\nfunction F(a)\r\nlocal s = ""\r\n\r\nr = 2.0\r\n'
        'if (a ~= 0) then\r\nreturn s .. I2S(a // 2)\r\nelseif (a == FourCC("hfoo")) then\r\nPrint("")\r\nend\r\n'
        "    print('raw')\r\nwhile (true) do\r\nif (a > 0x10) then break end\r\nend\r\nreturn nil\r\nend\r\n\r\n")
    indented = lua.transpile(jass, NATIVES, indented=True, blank_after_locals=False)
    assert "function F(a)\r\n    local s = \"\"\r\n    r = 2.0\r\n    if (a ~= 0) then\r\n        return" in indented


def test_style_of_editor_scripts():
    flat = "function CreateUnitsForPlayer0()\r\nlocal p = Player(0)\r\n\r\nend\r\n\r\nfunction main()\r\nInitBlizzard()\r\nend\r\n"
    assert lua.style(flat) == (False, True)
    indented = flat.replace("\r\nlocal", "\r\n    local").replace("\r\n\r\nend", "\r\nend").replace("\r\nInit", "\r\n    Init")
    assert lua.style(indented) == (True, False)
    assert lua.style("") == (False, True)
    assert lua.editor_generated("function main()\r\nend\r\nfunction config()\r\nend\r\n")
    assert not lua.editor_generated("print('hand written')\n")


def test_unsupported_jass_names_its_line():
    with pytest.raises(ValueError, match="line 2"):
        lua.transpile("function F takes nothing returns nothing\n    goto somewhere\nendfunction\n", NATIVES)
