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
    # ProbeBool and ProbeFinish ride along so the compiler checks them too
    user = ('local integer n = 3\ncall ProbeReport("n=" + I2S(n))\ncall BJDebugMsg("hi")\n'
            "call ProbeReport(ProbeBool(n > 2))\ncall ProbeFinish()")
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


def test_probe_finish_writes_the_report_once():
    """ProbeFinish() runs the report trigger at once; the timer's own run then finds it written."""
    for language in ("jass", "lua"):
        text = probe.script(language, 900, "")
        assert "ProbeFinish" in text and "ProbeBool" in text
        assert text.count("wc3mcpProbe_written = true") == 1
        assert text.index("if not wc3mcpProbe_userRan then") < text.index("wc3mcpProbe_written = true")
    assert "call TriggerExecute(gg_trg_wc3mcpProbe)" in probe.script("jass", 900, "")


def test_probe_expect_records_a_verdict():
    """A run answers pass/fail per check instead of text the caller has to read."""
    jass = probe.script("jass", 10, 'call ProbeExpect("gold rose", GetPlayerState(Player(0), '
                                    "PLAYER_STATE_RESOURCE_GOLD) > 500)")
    assert "function ProbeExpect takes string name, boolean ok returns nothing" in jass
    # buffered since 1.4: the report file is written at the end, so probe code cannot wipe the verdict
    assert 'call wc3mcpProbe_Line("check=pass:" + name)' in jass
    assert 'call wc3mcpProbe_Line("check=fail:" + name)' in jass
    lua = probe.script("lua", 5, 'ProbeExpect("hero alive", true)')
    assert 'wc3mcpProbe_Line("check=" .. (ok and "pass:" or "fail:") .. tostring(name))' in lua
    report = probe.parse(["probe=ok", "check=pass:gold rose", "check=fail:hero alive", "check=pass:wave spawned"])
    assert report["checks"] == {"gold rose": True, "hero alive": False, "wave spawned": True}
    assert report["checks_failed"] == ["hero alive"] and report["checks_passed"] == 2
    assert "checks" not in probe.parse(["probe=ok"])


def test_a_probe_buffers_its_lines_and_samples_handles():
    from wc3mcp.ops import probe

    text = probe.script("jass", 5.0, user='call PreloadGenClear()\ncall ProbeReport("kept")')
    body = text[text.index("function Trig_wc3mcpProbe_Actions"):]
    # the report file is opened after the user code, so the user's PreloadGenClear cannot wipe it
    assert body.index("call Trig_wc3mcpProbe_User()") < body.index("call PreloadGenClear()")
    assert "ProbeHandleCount" in probe.JASS_MESSAGES
    lines = ["probe=ok", "report=kept", "handles.start=1048800", "handles.end=1048920", "handles.seconds=120"]
    doc = probe.parse(lines)
    assert doc["reports"] == ["kept"]
    assert doc["handles"] == {"start": 1048800, "end": 1048920, "growth": 120, "seconds": 120, "per_minute": 60.0}


def test_probe_init_runs_at_map_init_and_can_keep_dialogs_shut(tmp_path):
    """A DialogDisplay pauses a single-player game, and a probe queued on a timer never runs behind it: probe_init
    runs inside map initialization, before the map's own initialization triggers show one."""
    from wc3mcp.gamedata.catalog import Catalog

    jass = probe.script("jass", 5.0, init="call ProbeSkipDialogs()")
    init = jass[jass.index("function InitTrig_wc3mcpProbe"):]
    assert init.splitlines()[1].strip() == "call Trig_wc3mcpProbe_Init()"
    assert "function Trig_wc3mcpProbe_Init takes nothing returns nothing\n    call ProbeSkipDialogs()" in jass
    routed = probe.route_messages("globals\nendglobals\ncall DialogDisplayBJ(true, d, p)\ncall DialogDisplay(p, d, "
                                  "true)\n")
    assert "call wc3mcpProbe_DialogDisplayBJ(true, d, p)" in routed and "call wc3mcpProbe_DialogDisplay(p, d, true)" \
        in routed.split("endglobals")[1].split("function wc3mcpProbe_DialogDisplayBJ")[1]
    lua = probe.script("lua", 5.0, init="ProbeSkipDialogs()")
    assert "Trig_wc3mcpProbe_Init()" in lua and "DialogDisplay = function(p, d, flag)" in lua

    maps = [p for p in ladder_maps() if open_sample("ladder:" + p.name).read("war3map.j") is not None]
    if not maps:
        pytest.skip("no JASS ladder map")
    source = tmp_path / maps[0].name
    shutil.copyfile(maps[0], source)
    probe.build(source, tmp_path / "probe" / maps[0].name, Catalog(_storage(), balance="Custom_V1"),
                init="call ProbeSkipDialogs()")   # compiles (build runs pjass and raises when it does not)


def test_what_a_person_does_during_a_run_is_reported():
    out = probe.parse(["probe=ok", "user.clicks=3", "userchat=0:-afk", "userchat=0:-lock"])
    assert out["user_input"] == {"chat": ["0:-afk", "0:-lock"], "clicks": 3}
    assert "user_input" not in probe.parse(["probe=ok", "user.clicks=0"])
    routed = probe.route_messages("globals\nendglobals\nfunction A takes nothing returns nothing\nendfunction\n")
    assert "EVENT_PLAYER_MOUSE_DOWN" in routed and "TriggerRegisterPlayerChatEvent" in routed
    assert "call wc3mcpProbe_WatchUsers()" in probe.script("jass", 5)


def test_the_report_says_when_the_script_started():
    assert 'call wc3mcpProbe_Line("script.started=" + R2S(TimerGetElapsed(wc3mcpProbe_clock)))' in probe.script(
        "jass", 5)
    jass = probe.script("jass", 5, user='call ProbeReport("x")')
    assert jass.index('"script.started="') < jass.index("call Trig_wc3mcpProbe_User()", jass.index(
        "function Trig_wc3mcpProbe_Actions"))
    assert '"script.started=" ..' in probe.script("lua", 5)
    assert probe.parse(["probe=ok", "script.started=60.125"])["script_started"] == 60.125


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
@pytest.mark.parametrize("language", ["jass", "lua"])
def test_a_protected_map_can_be_probed(tmp_path, language):
    """A protected map has no war3map.wtg: the probe goes straight into its script, before main."""
    from wc3mcp.errors import ToolError
    from wc3mcp.gamedata.catalog import Catalog
    from wc3mcp.ops import newmap, protect

    catalog = Catalog(_storage(), balance="Custom_V1")
    src = tmp_path / "Arena.w3x"
    newmap.new_map(src, catalog, 64, 64, "L", "Arena", "Tests", 2, language, "mpq", None)
    protected = protect.protect(src, catalog)["protected"]
    if language == "jass":
        user, functions, init = ('local integer n = 3\ncall ProbeReport("n=" + I2S(n))\ncall BJDebugMsg("hi")',
                                 "function Twice takes integer n returns integer\n    return n * 2\nendfunction\n",
                                 "call ProbeSkipDialogs()")
    else:
        user, functions, init = ('ProbeReport("n=" .. 3)\nBJDebugMsg("hi")',
                                 "function Twice(n)\n    return n * 2\nend\n", "ProbeSkipDialogs()")
    # build compiles the copy (pjass / the Lua parser) and raises when it does not
    copy = probe.build(protected, tmp_path / "probe" / "Arena.w3x", catalog, user=user, functions=functions, init=init)
    project = MapProject.open(copy)
    try:
        text = project.read("war3map.j" if language == "jass" else "war3map.lua").decode("utf-8", "replace")
    finally:
        project.close(discard=True)
    assert text.index("function Twice") < text.index("function Trig_wc3mcpProbe_User") < text.index("function main")
    assert "InitTrig_wc3mcpProbe()" in text[text.index("function main"):]
    if language == "jass":
        assert 'call wc3mcpProbe_Msg("hi")' in text and "trigger gg_trg_wc3mcpProbe = null" in text
    with pytest.raises(ToolError) as e:
        probe.build(protected, tmp_path / "probe2" / "Arena.w3x", catalog,
                    user="call NoSuchNative()" if language == "jass" else "local x = = 1")
    assert e.value.code == "probe_script_failed"
    if language == "jass":
        assert "probe_script" in e.value.hint


def test_inject_puts_the_probe_before_main_after_its_locals():
    text = ("globals\r\ninteger x=0\r\nendglobals\r\nfunction lIl takes nothing returns nothing\r\nendfunction\r\n"
            "function main takes nothing returns nothing\r\nlocal integer i=0\r\n// c\r\nlocal real r\r\n"
            "call lIl()\r\nendfunction\r\n")
    out = probe.inject(text, "jass", "function InitTrig_wc3mcpProbe takes nothing returns nothing\nendfunction\n")
    assert out.index("trigger gg_trg_wc3mcpProbe = null") < out.index("endglobals")
    assert out.index("function lIl") < out.index("function InitTrig_wc3mcpProbe") < out.index("function main")
    assert "local real r\r\ncall InitTrig_wc3mcpProbe()\ncall lIl()" in out
    lua = probe.inject("function lIl ( ) end function main ( ) lIl ( ) end\n", "lua", "function InitTrig_wc3mcpProbe() end")
    assert "function InitTrig_wc3mcpProbe() end\nfunction main ( ) InitTrig_wc3mcpProbe() " in lua

@pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
def test_the_shipped_regression_suite_compiles(tmp_path):
    from pathlib import Path

    from wc3mcp.gamedata.catalog import Catalog

    maps = [p for p in ladder_maps() if open_sample("ladder:" + p.name).read("war3map.j") is not None]
    if not maps:
        pytest.skip("no JASS ladder map")
    source = tmp_path / maps[0].name
    shutil.copyfile(maps[0], source)
    catalog = Catalog(_storage(), balance="Custom_V1")
    suite = Path(__file__).parents[2] / "skills" / "wc3-map-making" / "regress"
    files = [p for p in suite.glob("*.j") if not p.name.endswith(".functions.j")]
    assert len(files) >= 4
    for i, f in enumerate(files):
        helpers = f.with_suffix(".functions.j")
        # build runs pjass and raises probe_script_failed when the probe does not compile
        probe.build(source, tmp_path / f"probe{i}" / maps[0].name, catalog, user=f.read_text("utf-8"),
                    functions=helpers.read_text("utf-8") if helpers.is_file() else None)


def test_a_shown_dialog_is_written_to_its_own_file_at_once():
    """DialogDisplay pauses a single-player game: the wrapper writes its own file before the native runs, apart from
    the report and partial buffers."""
    jass = probe.route_messages("globals\nendglobals\n")
    shown = jass[jass.index("function wc3mcpProbe_DialogShown"):jass.index("function wc3mcpProbe_DialogDisplayBJ")]
    assert probe.DIALOG.replace("\\", "\\\\") in shown and 'Preload("dialog=" + R2S' in shown
    assert shown.index("dialog=suppressed") < shown.index("call wc3mcpProbe_DialogShown()") \
        < shown.index("call DialogDisplay(p, d, flag)")
    lua = probe.script("lua", 5.0)
    assert probe.DIALOG.replace("\\", "\\\\") in lua and 'Preload("count=" .. wc3mcpProbe_dialogs)' in lua


def test_probe_marks_screenshots_and_learns():
    """ProbeMark notes game time, ProbeScreenshot also asks the runner for a picture, ProbeLearn says why not."""
    for language in ("jass", "lua"):
        text = probe.script(language, 10, "")
        assert all(name in text for name in ("ProbeMark", "ProbeScreenshot", "ProbeLearn"))
        assert "{shot}" not in text and "wc3mcp\\\\shot.txt" in text
    out = probe.parse(["probe=ok", "mark=12.500:cast", "mark=40.000:impact", "report=x"])
    assert out["marks"] == [{"name": "cast", "time": 12.5}, {"name": "impact", "time": 40.0}]
