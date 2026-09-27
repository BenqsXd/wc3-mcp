import pytest

from corpus import HAVE_INSTALL, _storage
from wc3mcp.errors import ToolError
from wc3mcp.formats import w3i
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.mpq.reader import Archive
from wc3mcp.ops import newmap, protect
from wc3mcp.script import validate

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance="Custom_V1")


@pytest.mark.parametrize("language", ["jass", "lua"])
def test_protect_plays_hides_and_restores(tmp_path, catalog, language):
    src = tmp_path / "Arena.w3x"
    newmap.new_map(src, catalog, 64, 64, "L", "Arena", "Tests", 2, language, "mpq", None)
    original = src.read_bytes()
    result = protect.protect(src, catalog)
    assert src.read_bytes() == original

    arc = Archive.open(result["protected"])
    for name in ("war3map.wtg", "war3map.wct", "war3mapUnits.doo", "war3map.w3r", "(listfile)"):
        assert arc.find(name) is None, name
    assert w3i.parse(arc.read("war3map.w3i")).truncated
    script_name = "war3map.j" if language == "jass" else "war3map.lua"
    script = arc.read(script_name).decode("utf-8")
    assert "InitCustomTriggers" not in script and "CreateAllUnits" not in script and "main" in script
    check = (validate.validate_jass(script, catalog) if language == "jass" else validate.validate_lua(script))
    assert check["ok"], check["errors"][:3]
    with pytest.raises(ToolError) as e:
        protect.protect(result["protected"], catalog)
    assert e.value.code == "already_protected"

    src.unlink()
    restored = protect.unprotect(result["protected"])
    assert src.read_bytes() == original and restored["restored"] == str(src)
    with pytest.raises(ToolError) as e:
        protect.unprotect(src)   # not a file this server protected
    assert e.value.code == "not_ours"


def test_obfuscate_jass_keeps_what_the_game_looks_up_by_name():
    text = "\r\n".join([
        "globals",
        "    integer udg_Count = 0 // comment",
        "endglobals",
        "function Worker takes integer amount returns nothing",
        "    local integer i = amount",
        "    set udg_Count = i",
        "endfunction",
        "function Named takes nothing returns nothing",
        "    call BJDebugMsg(\"Named\")",
        "endfunction",
        "function main takes nothing returns nothing",
        "    call ExecuteFunc( \"Worker\" )",
        "endfunction", ""])
    out, count = protect.obfuscate_jass(text, {"BJDebugMsg", "ExecuteFunc"})
    for gone in ("udg_Count", "Worker", "amount", "comment", "    "):
        assert gone not in out, gone
    assert "function Named " in out and "function main " in out and count == 4   # udg_Count, Worker, amount, i
    computed, _ = protect.obfuscate_jass(text.replace('"Worker"', 'I2S(1)'), {"BJDebugMsg", "ExecuteFunc", "I2S"})
    assert "function Worker " in computed and "udg_Count" not in computed
