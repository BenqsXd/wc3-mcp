import re
import struct

import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps, open_sample, sample_map_ids
from wc3mcp.errors import ToolError
from wc3mcp.formats import w3c, w3e, w3r, w3s, wct, wtg
from wc3mcp.formats.wts import TriggerStrings
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.script import build, world

needs_install = pytest.mark.skipif(not HAVE_INSTALL, reason="needs TriggerData and SoundInfo from the install")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)


def wav(ms: int, rate: int = 22050) -> bytes:
    data = bytes(rate * ms // 1000 * 2)
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    return (b"RIFF" + struct.pack("<I", 4 + 24 + 8 + len(data)) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt
            + b"data" + struct.pack("<I", len(data)) + data)


def map_world(arc, catalog, audio=lambda path: None) -> world.World:
    def parsed(name, codec):
        data = arc.read(name)
        return codec.parse(data) if data is not None else None

    def label_row(label):
        try:
            return catalog.get("sound", label)["fields"]
        except ToolError:
            return None

    strings = arc.read("war3map.wts")
    return world.World(parsed("war3map.w3r", w3r), parsed("war3map.w3c", w3c), parsed("war3map.w3s", w3s),
                       parsed("war3map.w3e", w3e), TriggerStrings.parse(strings) if strings else TriggerStrings(),
                       label_row, audio)


def function(script: str, name: str) -> str | None:
    m = re.search(r"^function %s takes nothing returns nothing\r\n.*?^endfunction\r\n" % name, script, re.S | re.M)
    return m.group(0).replace("\r\n", "\n") if m else None


@needs_install
@pytest.mark.parametrize("map_id", sample_map_ids())
def test_sections_match_editor_scripts(map_id, catalog):
    arc = open_sample(map_id)
    script = arc.read("war3map.j")
    if script is None:
        pytest.skip("not a JASS map")
    script = script.decode("utf-8")
    parts = world.sections(map_world(arc, catalog), script)
    for name in ("InitSounds", "CreateRegions", "CreateCameras"):
        assert parts[name] == function(script, name), name
    if arc.read("war3map.wtg") is not None:
        td = catalog.trigger_data
        tf, ct = wtg.parse(arc.read("war3map.wtg"), td.arg_count), wct.parse(arc.read("war3map.wct"))
        assert build.splice(script, tf, ct, td, world=map_world(arc, catalog)) == script


@needs_install
def test_new_region_camera_and_sound_are_spliced_in(catalog):
    name = "(2)Amazonia.w3x"
    if name not in {p.name for p in ladder_maps()}:
        pytest.skip(f"{name} not in Documents")
    arc = open_sample("ladder:" + name)
    original = arc.read("war3map.j").decode("utf-8")
    td = catalog.trigger_data
    tf, ct = wtg.parse(arc.read("war3map.wtg"), td.arg_count), wct.parse(arc.read("war3map.wct"))
    w = map_world(arc, catalog, audio=lambda path: wav(1000))
    assert not (w.regions.regions or w.cameras.cameras) and w.sounds is None
    w.regions.regions.append(w3r.Region(-256, -256, 256, 256, "Arena", 0, weather=b"RAlr"))
    w.cameras.cameras.append(w3c.Camera("Intro", {**dict.fromkeys(w3c.FIELDS_V0, 0.0), "x": 128.0, "rotation": 90.0}))
    w.sounds = w3s.SoundFile(sounds=[w3s.Sound("gg_snd_Hello", "Units\\Human\\Footman\\FootmanYesAttack2.flac",
                                               "HeroAcksEAX", 2 | 4, 10, 10, 127, label="FootmanYesAttack")])
    text = build.splice(original, tf, ct, td, world=w)

    globals_ = text[text.index("\r\nglobals\r\n"):text.index("\r\nendglobals\r\n")]
    assert "    rect                    gg_rct_Arena               = null\r\n" in globals_
    assert "    camerasetup             gg_cam_Intro               = null\r\n" in globals_
    assert globals_.index("gg_snd_Hello") < globals_.index("gg_trg_")
    regions = function(text, "CreateRegions")
    assert "    set gg_rct_Arena = Rect( -256.0, -256.0, 256.0, 256.0 )\n" in regions
    assert "    set we = AddWeatherEffect( gg_rct_Arena, 'RAlr' )\n    call EnableWeatherEffect( we, true )\n" in regions
    assert "call CameraSetupSetDestPosition( gg_cam_Intro, 128.0, 0.0, 0.0 )" in function(text, "CreateCameras")
    sounds = function(text, "InitSounds")
    assert '    set gg_snd_Hello = CreateSound( "Units\\\\Human\\\\Footman\\\\FootmanYesAttack2.flac", false, true, ' \
           'true, 10, 10, "HeroAcksEAX" )\n' in sounds
    assert "    call SetSoundDuration( gg_snd_Hello, 1000 )\n" in sounds
    banners = [text.index(build._crlf(build.banner(t))) for t in ("Sound Assets", "Regions", "Cameras", "Triggers")]
    assert banners == sorted(banners) and text.index(build._crlf(build.banner("Unit Creation"))) > banners[0]
    main = text[text.index("function main takes"):]
    calls = [main.index(f"    call {fn}(  )") for fn in ("InitSounds", "CreateRegions", "CreateCameras", "InitBlizzard")]
    assert calls == sorted(calls)

    w.regions.regions.clear()
    w.cameras.cameras.clear()
    w.sounds = None
    assert build.splice(text, tf, ct, td, world=w) == original


def test_duplicate_names_are_declared_once():
    rf = w3r.RegionFile(regions=[w3r.Region(0, 0, 1, 1, "A", 0), w3r.Region(0, 0, 1, 1, "B", 1),
                                 w3r.Region(0, 0, 2, 2, "A", 2)])
    assert world.global_decls(rf, None, None) == [("rect", "gg_rct_A", "null"), ("rect", "gg_rct_B", "null")]
    assert world.create_regions(rf, None, {}).count("set gg_rct_A = Rect(") == 2


def test_audio_lengths():
    assert world.audio_ms(wav(1000)) == 1000
    info = bytes(10) + (44100 << 44 | 1 << 41 | 15 << 36 | 66150).to_bytes(8, "big") + bytes(16)
    assert world.audio_ms(b"fLaC" + b"\x80\x00\x00\x22" + info) == 1500
    ident = b"\x01vorbis" + struct.pack("<IBI", 0, 2, 48000) + bytes(16)
    ogg = b"OggS\x00\x02" + struct.pack("<q", 0) + bytes(14) + ident + b"OggS\x00\x04" + struct.pack("<q", 96000)
    assert world.audio_ms(ogg + bytes(20)) == 2000
    frame = b"\xff\xfb\x90\x00" + bytes(417 - 4)  # MPEG-1 layer III, 128 kbit/s, 44.1 kHz
    assert world.audio_ms(frame * 10) == (10 * 1152 - 529) * 1000 // 44100
    assert world.audio_ms(b"") is None and world.audio_ms(b"OggS") is None


def test_ground_height_interpolates_heights_and_cliff_layers():
    t = w3e.Terrain(11, "L", 0, [b"Ldrt"], [b"CLdi"], 2, 2, -128.0, -128.0, [0x2000, 0x2000 + 400, 0x2000, 0x2000],
                    [0] * 4, [0] * 4, [0] * 4, [2, 2, 3, 2])
    assert w3e.ground_height(t, -128, -128) == 0.0
    assert w3e.ground_height(t, 0, -128) == 100.0
    assert w3e.ground_height(t, -128, 0) == 128.0
    assert w3e.ground_height(t, -64, -64) == 57.0
    assert w3e.ground_height(t, 10_000, -10_000) == 100.0  # clamped to the map
