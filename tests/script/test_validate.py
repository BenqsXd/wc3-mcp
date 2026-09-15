import subprocess

import pytest

from corpus import HAVE_INSTALL, _storage, open_sample
from wc3mcp import config
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.script import validate

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
WARCHASERS = "casc:Maps/Scenario/(4)WarChasers.w3m"
VJASS = "\r\n".join([
    "globals", "endglobals", "library Foo initializer Init", "    struct Bar", "        integer x",
    "        static method create takes integer x returns thistype",
    "            local thistype this = thistype.allocate()", "            set this.x = x", "            return this",
    "        endmethod", "    endstruct", "    private function Init takes nothing returns nothing",
    "        local Bar b = Bar.create(5)", "        call BJDebugMsg(I2S(b.x))", "    endfunction", "endlibrary",
    "function main takes nothing returns nothing", "    call InitBlizzard()", "endfunction",
    "function config takes nothing returns nothing", "endfunction", ""])


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)


def jasshelper_processes() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq jasshelper.exe", "/NH"], capture_output=True, text=True).stdout
    return out.lower().count("jasshelper.exe")


def test_tools_are_copied_out_of_the_install(catalog):
    tools = validate.tool_dir(catalog)
    assert tools.is_relative_to(config.home())
    assert {"pjass.exe", "jasshelper.exe", "sfmpq.dll", "common.j", "Blizzard.j"} <= {p.name for p in tools.iterdir()}


def test_pjass_accepts_editor_scripts_and_locates_errors(catalog):
    script = open_sample(WARCHASERS).read("war3map.j").decode("utf-8")
    clean = validate.validate_jass(script, catalog)
    assert clean["ok"] and clean["errors"] == [] and clean["tool"].startswith("pjass")
    anchor = "function Trig_RoboX_Actions takes nothing returns nothing\r\n"
    broken = validate.validate_jass(script.replace(anchor, anchor + "    set udg_DoesNotExist = 5\r\n", 1), catalog)
    assert not broken["ok"]
    [error] = broken["errors"]
    assert error["message"].startswith("Undeclared variable udg_DoesNotExist")  # pjass may add "Maybe you meant ..."
    assert (error["section"], error["trigger"], error["source"]) == ("Triggers", "RoboX", "set udg_DoesNotExist = 5")


def test_vjass_goes_through_jasshelper(catalog):
    assert validate.is_vjass(VJASS) and not validate.is_vjass("function main takes nothing returns nothing\r\n")
    result = validate.validate_jass(VJASS, catalog)
    assert result["ok"] and result["tool"] == "jasshelper --scriptonly", result
    broken = validate.validate_jass(VJASS.replace("set this.x = x", "set this.y = x"), catalog)
    assert not broken["ok"] and [e["message"] for e in broken["errors"]] == ["y is not a member of Bar"]
    assert jasshelper_processes() == 0


def test_lua_syntax():
    assert validate.validate_lua("function f()\nend\n")["ok"]
    result = validate.validate_lua("function f(\nend end")
    assert not result["ok"] and result["tool"] == "luacheck" and result["errors"][0]["line"] == 2
