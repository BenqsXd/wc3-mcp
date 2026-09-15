import pytest

from corpus import open_sample, sample_map_ids
from wc3mcp.formats import w3c, w3r, w3s
from wc3mcp.formats.binary import FormatError

CODECS = {"war3map.w3r": w3r, "war3map.w3c": w3c, "war3map.w3s": w3s}


def _regions(version: int) -> w3r.RegionFile:
    return w3r.RegionFile(version, [
        w3r.Region(-2976.0, -4256.0, -2912.0, -4192.0, "Alicia", 124, b"RAlr", "LordaeronSummerDay", b"\xff\x80\x80\xff"),
        w3r.Region(0.0, 0.5, 128.0, 256.25, "Äpfel", 0)])


def _cameras(version: int) -> w3c.CameraFile:
    fields = w3c.FIELDS_V3 if version >= 3 else w3c.FIELDS_V0
    cam = w3c.Camera("Close Arthas", {f: i + 0.5 for i, f in enumerate(fields)}, camera_type=1 if version >= 3 else 0)
    return w3c.CameraFile(version, [cam, w3c.Camera("Empty", dict.fromkeys(fields, 0.0))])


def _sounds() -> w3s.SoundFile:
    plain = w3s.Sound("gg_snd_DefendCaster", "Abilities\\Spells\\Human\\Defend\\DefendCaster.flac", eax="SpellsEAX",
                      label="Defend")
    dialogue = w3s.Sound("gg_snd_H01Grunt21", "Sound\\Dialogue\\H01Grunt21.flac", flags=6, volume=100, pitch=1.0,
                         channel=5, min_distance=600.0, max_distance=10000.0, distance_cutoff=3000.0,
                         dialogue_text_key=99, dialogue_speaker_key=98, unknown_s2="d", unknown_i1=1,
                         speaker_unit="ogru", facial_animation_label="H01Grunt21",
                         facial_animation_group_label="Map-Grunt",
                         facial_animation_set_path="Sound/Dialogue/FaceAnimation/Grunt.animset", unknown_i2=0)
    odd = w3s.Sound("gg_snd_Odd", "a.wav", name2="gg_snd_Other", path2="b.wav", unknown_s1="x")
    return w3s.SoundFile(3, [plain, dialogue, odd])


def test_regions_roundtrip_both_versions():
    for version in w3r.VERSIONS:
        rf = _regions(version)
        assert w3r.parse(w3r.serialize(rf)) == rf


def test_region_v7_extra_bytes():
    rf = _regions(7)
    rf.regions[0].extra = b"12345678"
    data = w3r.serialize(rf)
    assert w3r.parse(data).regions[0].extra == b"12345678"
    assert len(data) == len(w3r.serialize(_regions(5))) + 16


def test_cameras_roundtrip_both_versions():
    for version in w3c.VERSIONS:
        cf = _cameras(version)
        assert w3c.parse(w3c.serialize(cf)) == cf


def test_camera_missing_field_cannot_be_written():
    cf = _cameras(3)
    del cf.cameras[0].values["z_absolute"]
    with pytest.raises(FormatError):
        w3c.serialize(cf)


def test_sounds_roundtrip_and_repeated_name_and_path():
    sf = _sounds()
    back = w3s.parse(w3s.serialize(sf))
    assert back == sf
    assert back.sounds[0].name2 is None and back.sounds[2].name2 == "gg_snd_Other"
    assert back.sounds[0].pitch == w3s.UNSET


@pytest.mark.parametrize("module, version", [(w3r, 6), (w3c, 1), (w3s, 2)])
def test_unknown_versions_raise(module, version):
    with pytest.raises(FormatError):
        module.parse(version.to_bytes(4, "little") + bytes(4))


@pytest.mark.parametrize("module, model", [(w3r, _regions(7)), (w3c, _cameras(3)), (w3s, _sounds())])
def test_truncated_or_trailing_data_raises(module, model):
    data = module.serialize(model)
    with pytest.raises(FormatError):
        module.parse(data[:-3])
    with pytest.raises(FormatError):
        module.parse(data + b"\0")


@pytest.mark.parametrize("name", sorted(CODECS))
@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_roundtrip_is_byte_exact(map_id, name):
    data = open_sample(map_id).read(name)
    if data is None:
        pytest.skip(f"no {name}")
    codec = CODECS[name]
    model = codec.parse(data)
    assert model.version in codec.VERSIONS
    assert codec.serialize(model) == data
