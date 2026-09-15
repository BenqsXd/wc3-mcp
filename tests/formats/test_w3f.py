from pathlib import Path

import pytest

from wc3mcp.formats import w3f
from wc3mcp.formats.binary import FormatError

DATA = Path(__file__).parent / "data" / "campaign"
SAMPLES = sorted(p.name for p in DATA.glob("*.w3f"))   # saved by the Campaign Editor, one change set each


@pytest.mark.parametrize("name", SAMPLES)
def test_editor_samples_round_trip(name):
    data = (DATA / name).read_bytes()
    assert w3f.serialize(w3f.parse(data)) == data


def test_new_campaign_matches_the_editor():
    assert w3f.serialize(w3f.CampaignInfo()) == (DATA / "default.w3f").read_bytes()


def test_decoded_editor_values():
    loading = w3f.parse((DATA / "loading_screen.w3f").read_bytes())
    assert (loading.background, loading.ambient_sound, loading.fog_style, loading.cursor, loading.background_version,
            loading.fog_over_sky) == (2, 4, 2, 2, 2, 1)   # Orc screen, Night Elf sound, Exponential 2, Undead, Reforged
    assert [round(getattr(loading, f), 2) for f in w3f.FOG_FLOATS + w3f.FOG_FLOATS_2] == [
        111, 222, 0.33, 444, 555, 666, 777, 0.88]

    buttons = w3f.parse((DATA / "buttons.w3f").read_bytes())
    assert buttons.flags == w3f.FLAG_VARIABLE_DIFFICULTY and buttons.name == "TRIGSTR_001"
    assert buttons.minimap_path == "UI\\Widgets\\Glues\\Minimap-CustomCampaign-Undead"
    assert buttons.buttons == [w3f.Button(1, "TRIGSTR_005", "TRIGSTR_006", "Chapter One.w3x"),
                               w3f.Button(2, "TRIGSTR_007", "TRIGSTR_008", "Chapter Two.w3x")]
    assert buttons.maps == [w3f.CampaignMap("", "Chapter One.w3x"), w3f.CampaignMap("", "Chapter Two.w3x")]

    color = w3f.parse((DATA / "fog_color_minimap_from_map.w3f").read_bytes())
    assert color.fog_color == bytes([30, 20, 10, 255]) and color.minimap_path == "Chapter Two.w3x"
    assert color.flags == w3f.FLAG_VARIABLE_DIFFICULTY | w3f.FLAG_MINIMAP_FROM_MAP

    imported = w3f.parse((DATA / "imported_background_ambient.w3f").read_bytes())
    assert (imported.background, imported.background_path) == (-1, "war3campImported\\intro.webm")
    assert (imported.ambient_sound, imported.ambient_sound_path) == (-1, "war3campImported\\click.flac")
    assert imported.flags & w3f.FLAG_IMPORTED_AMBIENT
    minimap = w3f.parse((DATA / "imported_background_minimap.w3f").read_bytes())
    assert minimap.minimap_path == "war3campImported\\minimap.tga" and minimap.flags == w3f.FLAG_VARIABLE_DIFFICULTY


def test_rejects_other_versions_and_trailing_bytes():
    data = (DATA / "default.w3f").read_bytes()
    with pytest.raises(FormatError, match="version 1"):
        w3f.parse(b"\x01\x00\x00\x00" + data[4:])
    with pytest.raises(FormatError):
        w3f.parse(data + b"\0")
