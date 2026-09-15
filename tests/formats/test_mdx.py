import struct

import pytest

from corpus import HAVE_INSTALL, RARE_MODELS, _storage, sample_models
from wc3mcp.formats import mdx
from wc3mcp.formats.binary import FormatError

needs_install = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@needs_install
def test_game_models_round_trip():
    s = _storage()
    names = sample_models(s, others=60)
    assert len(names) >= len(RARE_MODELS) - 3 + 60
    seen_tags, seen_versions = set(), set()
    for name in names:
        data = s.read(name)
        model = mdx.parse(data)
        assert mdx.serialize(model) == data, name
        seen_tags.update(tag for tag, _ in model["chunks"])
        seen_versions.add(model["version"])
    assert {"GEOS", "BONE", "MTLS", "PRE2", "RIBB", "CAMS", "CLID", "CORN", "FAFX", "BPOS", "TXAN", "PREM"} <= seen_tags
    assert {1600, 1700, 1800} <= seen_versions


@needs_install
def test_model_fields_read_as_expected():
    s = _storage()
    model = mdx.parse(s.read(s.resolve("Units/Human/Footman/Footman.mdx")))
    info = mdx.chunk(model, "MODL")
    assert info["name"] == "Footman" and model["version"] == 1800
    names = [seq["name"] for seq in mdx.chunk(model, "SEQS")]
    assert "Stand - 1" in names and "Death" in names
    assert any(t["replaceable_id"] == 1 for t in mdx.chunk(model, "TEXS"))
    geoset = mdx.chunk(model, "GEOS")[0]
    assert len(geoset["vertices"]) == len(geoset["normals"]) and max(geoset["faces"]) < len(geoset["vertices"]) // 3


def _tiny(version: int = 800) -> bytes:
    model = {"version": version, "chunks": [
        ["MODL", {"name": "Tiny", "animation_file": "", "bounds_radius": 1.0, "minimum": [0.0] * 3, "maximum": [1.0] * 3,
                  "blend_time": 150}],
        ["GLBS", [1000]], ["ABCD", b"kept"]]}
    return mdx.serialize(model)


def test_small_model_and_unknown_chunks():
    data = _tiny()
    model = mdx.parse(data)
    assert mdx.chunk(model, "ABCD") == b"kept" and mdx.chunk(model, "GLBS") == [1000]
    assert mdx.serialize(model) == data


@pytest.mark.parametrize("data, message", [
    (b"MDLY", "not an MDX model"),
    (_tiny()[:-2], "runs past the end"),
    (_tiny().replace(b"GLBS\x04\x00\x00\x00", b"SEQS\x04\x00\x00\x00"), "MDX chunk SEQS"),
    (b"MDLXVERS" + struct.pack("<II", 4, 800) + b"BONE" + struct.pack("<I", 12) + struct.pack("<I", 200) + bytes(8),
     "MDX chunk BONE"),
])
def test_errors(data, message):
    with pytest.raises(FormatError, match=message):
        mdx.parse(data)
