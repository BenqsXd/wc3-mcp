import pytest

from corpus import HAVE_INSTALL, _storage, sample_models
from wc3mcp.formats import mdl, mdx
from wc3mcp.formats.binary import FormatError

BOX = r'''// a hand-written model in the classic dialect
Version {
	FormatVersion 800,
}
Model "Box" {
	NumGeosets 1,
	BlendTime 150,
	MinimumExtent { -1, -1, 0 },
	MaximumExtent { 1, 1, 2 },
}
Sequences 1 {
	Anim "Stand" {
		Interval { 0, 1000 },
		MoveSpeed 0,
	}
}
Textures 1 {
	Bitmap {
		Image "Textures\Footman.blp",
		ReplaceableId 1,
		WrapHeight,
	}
}
Materials 1 {
	Material {
		Layer {
			FilterMode Blend,
			TwoSided,
			static TextureID 0,
			Alpha 2 {
				Linear,
				0: 1,
				500: 0.5,
			}
		}
	}
}
Geoset {
	Vertices 3 {
		{ 0, 0, 0 },
		{ 1, 0, 0 },
		{ 0, 1, 0 },
	}
	Normals 3 {
		{ 0, 0, 1 },
		{ 0, 0, 1 },
		{ 0, 0, 1 },
	}
	TVertices 3 {
		{ 0, 0 },
		{ 1, 0 },
		{ 0, 1 },
	}
	VertexGroup {
		0,
		0,
		0,
	}
	Faces 1 3 {
		Triangles {
			{ 0, 1, 2 },
		}
	}
	Groups 1 1 {
		Matrices { 0 },
	}
	MaterialID 0,
	SelectionGroup 0,
}
Bone "Root" {
	ObjectId 0,
	GeosetId 0,
	GeosetAnimId None,
	DontInherit { Rotation },
	Rotation 1 {
		Hermite,
		GlobalSeqId 0,
		0: { 0, 0, 0, 1 },
			InTan { 0, 0, 0, 1 },
			OutTan { 0, 0, 0, 1 },
	}
}
Attachment "Head Ref" {
	ObjectId 1,
	Parent 0,
	AttachmentID 0,
	Visibility 1 {
		DontInterp,
		0: 1,
	}
}
PivotPoints 2 {
	{ 0, 0, 0 },
	{ 0, 0, 1.5 },
}
GlobalSequences 1 {
	Duration 1000,
}
'''


def test_reads_a_hand_written_model():
    model = mdl.parse(BOX)
    data = mdx.serialize(model)
    back = mdx.parse(data)
    assert back == model and back["version"] == 800
    assert mdx.chunk(back, "MODL")["name"] == "Box" and mdx.chunk(back, "GLBS") == [1000]
    texture, = mdx.chunk(back, "TEXS")
    assert texture == {"replaceable_id": 1, "path": "Textures\\Footman.blp", "flags": 2}
    layer = mdx.chunk(back, "MTLS")[0]["layers"][0]
    assert (layer["filter_mode"], layer["flags"], layer["tracks"][0]["keys"]) == (2, 0x10, [[0, [1.0]], [500, [0.5]]])
    geoset, = mdx.chunk(back, "GEOS")
    assert geoset["faces"] == [0, 1, 2] and geoset["face_types"] == [4] and geoset["uvs"] == [[0.0, 0.0, 1.0, 0.0, 0.0, 1.0]]
    bone, = mdx.chunk(back, "BONE")
    assert (bone["flags"], bone["geoset_animation_id"], bone["tracks"][0]["global_sequence"]) == (0x104, mdx.NO_ID, 0)
    attachment, = mdx.chunk(back, "ATCH")
    assert (attachment["node"]["parent_id"], attachment["node"]["flags"], attachment["tracks"][0]["tag"]) == (0, 0x800, "KATV")
    assert mdx.chunk(back, "PIVT")[1] == [0.0, 0.0, 1.5]
    assert mdl.parse(mdl.serialize(model)) == model


def test_written_text_is_plain_mdl():
    text = mdl.serialize(mdl.parse(BOX)).decode()
    assert "//@" not in text   # nothing needed the extension lines
    assert 'Bone "Root" {' in text and "\tDontInherit { Rotation }," in text and "\t\t0: { 0, 0, 0, 1 }," in text


def test_extension_lines_keep_what_mdl_cannot_say():
    model = mdl.parse(BOX)
    bone = mdx.chunk(model, "BONE")[0]
    bone["flags"] |= 0x40000000
    bone["name"] = b"Root\0junk" + bytes(71)
    model["chunks"].append(["ABCD", b"\x01\x02"])
    model["chunks"].append(["BONE", []])
    text = mdl.serialize(model)
    assert b'//@ flags 1073742084' in text and b'//@ raw {"tag":"ABCD","data":{"hex":"0102"}}' in text
    assert mdl.parse(text) == model
    assert mdx.serialize(mdl.parse(text)) == mdx.serialize(model)


@pytest.mark.parametrize("text, message", [
    ("Version { FormatVersion 800, }\nGeoset { Wobble 3, }", "unknown MDL token 'Wobble' in Geoset"),
    ("Model \"x\" {", "ends inside a block"),
    ("Bone \"b\" { Rotation 1 { Hermite, 0: { 0, 0, 0, 1 }, } }", "InTan and OutTan"),
    ("Spaceship { }", "unknown MDL block 'Spaceship'"),
])
def test_errors(text, message):
    with pytest.raises(FormatError, match=message):
        mdl.parse(text)


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")
def test_game_models_survive_mdx_to_mdl_to_mdx():
    s = _storage()
    for name in sample_models(s, others=8):
        data = s.read(name)
        text = mdl.serialize(mdx.parse(data))
        assert mdx.serialize(mdl.parse(text)) == data, name
