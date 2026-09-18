import pytest

from corpus import HAVE_INSTALL, _storage
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.audio import sound_add
from wc3mcp.ops.elements import elements_list
from wc3mcp.ops.newmap import new_map
from wc3mcp.ops.script import script_build

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance="Custom_V1")


@pytest.fixture
def project(tmp_path, catalog):
    return new_map(str(tmp_path / "Audio.w3x"), catalog, width=32, height=32, tileset="L", players=1)


def test_a_local_sound_is_imported_registered_and_playable(project, catalog, tmp_path):
    wav = tmp_path / "horn.wav"
    wav.write_bytes(b"RIFF" + b"\0" * 40)
    doc = sound_add(project, catalog, "Horn", source=str(wav), kind="sound3d")
    assert doc["variable"] == "gg_snd_Horn" and doc["imported_bytes"] == 44
    assert doc["path"] == "war3mapImported\horn.wav" and "AttachSoundToUnit" in doc["script"]
    entry = doc["sound"]
    assert entry["is_3d"] and entry["stop_when_out_of_range"] and entry["max_distance"] == 8000.0
    assert any(f["name"].lower() == "war3mapimported\horn.wav" for f in project.list_files())
    script_build(project, catalog)
    assert "gg_snd_Horn" in project.read("war3map.j").decode("utf-8", "replace")


def test_the_kind_chooses_the_settings_and_the_script(project, catalog):
    music = sound_add(project, catalog, "Theme", game_path="Sound/Music/mp3Music/ArthasTheme.mp3", kind="music")
    assert music["imported_bytes"] == 0 and "PlayMusic" in music["script"]
    assert music["sound"]["music"] and music["sound"]["looping"]
    ambient = sound_add(project, catalog, "Wind", game_path="Sound/Music/mp3Music/BloodElfTheme.mp3",
                        kind="ambient", settings={"volume": 60})
    assert ambient["sound"]["looping"] and ambient["sound"]["is_3d"] and ambient["sound"]["volume"] == 60
    assert len(elements_list(project, "sound")["items"]) == 2


def test_sound_add_refuses_what_the_game_cannot_play(project, catalog, tmp_path):
    bad = tmp_path / "horn.txt"
    bad.write_text("not audio")
    for kwargs, code in (({"name": "A", "source": str(bad)}, "bad_value"),
                         ({"name": "A", "source": str(tmp_path / "missing.wav")}, "not_found"),
                         ({"name": "A"}, "bad_value"),
                         ({"name": "A", "source": str(bad), "game_path": "Sound/Music/mp3Music/Comradeship.mp3"}, "bad_value"),
                         ({"name": "bad name", "game_path": "Sound/Music/mp3Music/Comradeship.mp3"}, "bad_value"),
                         ({"name": "A", "game_path": "Sound/Music/mp3Music/Comradeship.mp3", "kind": "siren"}, "bad_value"),
                         ({"name": "A", "game_path": "Sound/Music/mp3Music/Comradeship.mp3", "settings": {"loudness": 5}}, "bad_value")):
        with pytest.raises(ToolError) as e:
            sound_add(project, catalog, **kwargs)
        assert e.value.code == code, kwargs
