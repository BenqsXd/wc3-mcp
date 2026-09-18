import shutil

import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps, open_sample
from wc3mcp.ops import probe
from wc3mcp.ops.triggers import triggers_tree
from wc3mcp.project.workspace import MapProject


def test_script_reports_through_preload():
    jass = probe.script("jass", 10)
    assert "function InitTrig_wc3mcpProbe takes nothing returns nothing" in jass
    assert r'call PreloadGenEnd("wc3mcp\\probe.txt")' in jass and "TriggerRegisterTimerEvent" in jass
    lua = probe.script("lua", 5)
    assert "function InitTrig_wc3mcpProbe()" in lua and r'PreloadGenEnd("wc3mcp\\probe.txt")' in lua


def test_parse_report():
    assert probe.parse(["probe=ok", "seconds=10.00", "player0.units=12", "player0.heroes=1", "message0=hi=there",
                        "message1=second"]) == {"probe": "ok", "seconds": "10.00", "player0.units": 12,
                                                "player0.heroes": 1, "messages": ["hi=there", "second"], "reports": []}
    assert probe.parse(["report=abc", "report+=def", "report=x"])["reports"] == ["abcdef", "x"]


def test_debug_messages_reach_the_report():
    script = ("globals\n    integer udg_x = 0\nendglobals\nfunction A takes nothing returns nothing\n"
              '    call BJDebugMsg("a")\n    call BJDebugMsgX()\n'
              '    call DisplayTimedTextToPlayer(GetLocalPlayer(), 0, 0, 5, "b")\nendfunction\n')
    routed = probe.route_messages(script)
    assert routed.index("string array wc3mcpProbe_messages") < routed.index("endglobals")
    assert routed.index("function wc3mcpProbe_Msg") < routed.index("function A")
    assert 'call wc3mcpProbe_Msg("a")' in routed and "call BJDebugMsgX()" in routed
    assert 'call wc3mcpProbe_DisplayTimedTextToPlayer(GetLocalPlayer(), 0, 0, 5, "b")' in routed
    assert routed.count("call BJDebugMsg(s)") == 1   # the route itself still shows the message
    assert '"DisplayTimedTextToPlayer"' in probe.script("lua", 5) and "heroes" in probe.script("jass", 5)


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
def test_build_makes_a_copy_that_reports(tmp_path):
    from wc3mcp.gamedata.catalog import Catalog

    maps = [p for p in ladder_maps() if open_sample("ladder:" + p.name).read("war3map.wtg") is not None]
    if not maps:
        pytest.skip("no ladder map with triggers")
    source = tmp_path / maps[0].name
    shutil.copyfile(maps[0], source)
    copy = probe.build(source, tmp_path / "probe" / maps[0].name, Catalog(_storage(), balance="Custom_V1"))
    assert copy.is_file() and source.read_bytes() != copy.read_bytes()
    project = MapProject.open(copy)
    try:
        assert probe.NAME in [t["name"] for t in triggers_tree(project, Catalog(_storage()))["triggers"]]
        text = project.read("war3map.j").decode("utf-8", "replace")
        assert "PreloadGenEnd" in text and "function wc3mcpProbe_Msg" in text
        assert any(f["name"].lower() == "war3mapmap.blp" for f in project.list_files())
    finally:
        project.close(discard=True)


def test_probe_script_runs_the_callers_code():
    jass = probe.script("jass", 10, "local integer n = 3\ncall ProbeReport(\"n=\" + I2S(n))")
    assert jass.index("function ProbeReport takes string s") < jass.index("function Trig_wc3mcpProbe_User")
    assert "    local integer n = 3\n" in jass and jass.index("function Trig_wc3mcpProbe_User") < jass.index(
        "function Trig_wc3mcpProbe_Actions")
    assert jass.count("call Trig_wc3mcpProbe_User()") == 1 and "call Trig_wc3mcpProbe_User()" not in probe.script("jass", 10)
    lua = probe.script("lua", 5, "local t = {1, 2}\nProbeReport(#t)")
    assert "function ProbeReport(s)" in lua and "    local t = {1, 2}\n" in lua and "    Trig_wc3mcpProbe_User()\n" in lua


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
def test_probe_script_compiles_into_the_copy(tmp_path):
    from wc3mcp.errors import ToolError
    from wc3mcp.gamedata.catalog import Catalog

    maps = [p for p in ladder_maps() if open_sample("ladder:" + p.name).read("war3map.j") is not None]
    if not maps:
        pytest.skip("no JASS ladder map")
    source = tmp_path / maps[0].name
    shutil.copyfile(maps[0], source)
    catalog = Catalog(_storage(), balance="Custom_V1")
    user = 'local integer n = 3\ncall ProbeReport("n=" + I2S(n))\ncall BJDebugMsg("hi")'
    copy = probe.build(source, tmp_path / "probe" / maps[0].name, catalog, user=user)
    project = MapProject.open(copy)
    try:
        text = project.read("war3map.j").decode("utf-8", "replace")
        assert "call ProbeReport(\"n=\" + I2S(n))" in text and 'call wc3mcpProbe_Msg("hi")' in text
    finally:
        project.close(discard=True)
    with pytest.raises(ToolError) as e:
        probe.build(source, tmp_path / "probe2" / maps[0].name, catalog, user="call NoSuchNative()")
    assert e.value.code == "probe_script_failed" and "probe_script" in e.value.hint
    functions = ("function OnBuild takes nothing returns nothing\n"
                 '    call DisplayTimedTextToPlayer(GetLocalPlayer(), 0, 0, 5, "built")\nendfunction\n')
    user = ("local trigger t = CreateTrigger()\n"
            "call TriggerRegisterAnyUnitEventBJ(t, EVENT_PLAYER_UNIT_CONSTRUCT_FINISH)\n"
            "call TriggerAddAction(t, function OnBuild)\n"
            'call ProbeCountEvent(EVENT_PLAYER_UNIT_CONSTRUCT_START, "starts")\n'
            "call TriggerSleepAction(5)\n"
            'call ProbeReport("starts=" + I2S(ProbeEventCount("starts")))')
    copy = probe.build(source, tmp_path / "probe3" / maps[0].name, catalog, user=user, functions=functions)
    project = MapProject.open(copy)
    try:
        text = project.read("war3map.j").decode("utf-8", "replace")
        assert text.index("function OnBuild") < text.index("function Trig_wc3mcpProbe_User")
        assert "hashtable wc3mcpProbe_table" in text and "wc3mcpProbe_DisplayTimedTextToPlayer(GetLocalPlayer()" in text
    finally:
        project.close(discard=True)
    with pytest.raises(ToolError) as e:
        probe.build(source, tmp_path / "probe4" / maps[0].name, catalog, functions="function Broken takes nothing")
    assert e.value.code == "probe_script_failed" and "probe_functions" in e.value.hint


def test_probe_script_can_call_the_maps_own_functions(tmp_path):
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops.triggers import triggers_edit

    maps = [p for p in ladder_maps() if open_sample("ladder:" + p.name).read("war3map.j") is not None]
    if not maps:
        pytest.skip("no JASS ladder map")
    source = tmp_path / maps[0].name
    shutil.copyfile(maps[0], source)
    catalog = Catalog(_storage(), balance="Custom_V1")
    project = MapProject.open(source)
    try:   # a helper in a category after the map's first one: the probe must come after it
        triggers_edit(project, catalog, [{"op": "category", "name": "Systems"}, {
            "op": "trigger", "name": "Helpers", "category": "Systems",
            "script": "function MapHelper takes nothing returns integer\n    return 7\nendfunction\n"}])
        copy = probe.build(source, tmp_path / "probe" / maps[0].name, catalog, project=project,
                           user='call ProbeReport(I2S(MapHelper()))')
    finally:
        project.close(discard=True)
    text = MapProject.open(copy)
    try:
        script = text.read("war3map.j").decode("utf-8", "replace")
        assert script.index("function MapHelper") < script.index("function Trig_wc3mcpProbe_User")
    finally:
        text.close(discard=True)


def test_probe_expect_records_a_verdict():
    """A run answers pass/fail per check instead of text the caller has to read."""
    jass = probe.script("jass", 10, 'call ProbeExpect("gold rose", GetPlayerState(Player(0), '
                                    "PLAYER_STATE_RESOURCE_GOLD) > 500)")
    assert "function ProbeExpect takes string name, boolean ok returns nothing" in jass
    assert 'call Preload("check=pass:" + name)' in jass and 'call Preload("check=fail:" + name)' in jass
    lua = probe.script("lua", 5, 'ProbeExpect("hero alive", true)')
    assert 'Preload("check=" .. (ok and "pass:" or "fail:") .. tostring(name))' in lua
    report = probe.parse(["probe=ok", "check=pass:gold rose", "check=fail:hero alive", "check=pass:wave spawned"])
    assert report["checks"] == {"gold rose": True, "hero alive": False, "wave spawned": True}
    assert report["checks_failed"] == ["hero alive"] and report["checks_passed"] == 2
    assert "checks" not in probe.parse(["probe=ok"])
