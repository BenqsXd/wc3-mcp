"""MDX models (MDLX chunks). Every chunk is read into plain Python data: dicts of named fields in file order, lists of
objects, animation tracks as {"tag", "interpolation", "global_sequence", "keys": [[frame, value, in_tan, out_tan]]}.
Fixed-length names that carry bytes after their terminator stay raw bytes, so serialize(parse(data)) == data."""
import struct

from .binary import FormatError

MAGIC = b"MDLX"
NO_ID = 0xFFFFFFFF
EXTENT = (("bounds_radius", "f"), ("minimum", "3f"), ("maximum", "3f"))

# value type of every animation track tag: number of floats, or "u" for an integer
TRACKS = {
    "KMTF": "u", "KMTA": 1, "KMTE": 1, "KFC3": 3, "KFCA": 1, "KFTC": 1,
    "KTAT": 3, "KTAR": 4, "KTAS": 3,
    "KGAO": 1, "KGAC": 3,
    "KGTR": 3, "KGRT": 4, "KGSC": 3,
    "KLAS": 1, "KLAE": 1, "KLAC": 3, "KLAI": 1, "KLBI": 1, "KLBC": 3, "KLAV": 1,
    "KATV": 1,
    "KPEE": 1, "KPEG": 1, "KPLN": 1, "KPLT": 1, "KPEL": 1, "KPES": 1, "KPEV": 1,
    "KP2E": 1, "KP2G": 1, "KP2L": 1, "KP2S": 1, "KP2V": 1, "KP2R": 1, "KP2N": 1, "KP2W": 1,
    "KRVS": 1, "KRHA": 1, "KRHB": 1, "KRAL": 1, "KRCO": 3, "KRTX": "u",
    "KCTR": 3, "KTTR": 3, "KCRL": 1,
    "KPPA": 1, "KPPC": 3, "KPPE": 1, "KPPL": 1, "KPPS": 1, "KPPV": 1,
    # one-float camera tracks without a K prefix, found in a few game models (ShroomsBlue, SpiritTowerDeath)
    "IDUF": 1, "ELAF": 1, "PTSF": 1,
}


class Reader:
    def __init__(self, data: bytes, pos: int = 0, end: int | None = None):
        self.data, self.pos, self.end = data, pos, len(data) if end is None else end

    def take(self, n: int) -> bytes:
        if self.pos + n > self.end:
            raise FormatError(f"MDX data ends early at offset {self.pos} (need {n} bytes)")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def unpack(self, fmt: str):
        size = struct.calcsize("<" + fmt)
        return struct.unpack("<" + fmt, self.take(size))

    def u32(self) -> int:
        return self.unpack("I")[0]

    def tag(self) -> str:
        return self.take(4).decode("latin-1")

    def peek_tag(self) -> str | None:
        return self.data[self.pos:self.pos + 4].decode("latin-1") if self.pos + 4 <= self.end else None

    def text(self, n: int):
        raw = self.take(n)
        cut = raw.find(b"\0")
        if cut < 0 or raw[cut:].strip(b"\0"):
            return raw   # no terminator or bytes after it: keep as stored
        return raw[:cut].decode("utf-8", "surrogateescape")


class Writer:
    def __init__(self):
        self.parts: list[bytes] = []

    def raw(self, b: bytes) -> None:
        self.parts.append(b)

    def pack(self, fmt: str, *values) -> None:
        self.parts.append(struct.pack("<" + fmt, *values))

    def text(self, value, n: int) -> None:
        raw = value if isinstance(value, bytes) else value.encode("utf-8", "surrogateescape")
        if len(raw) > n or (not isinstance(value, bytes) and len(raw) == n):
            raise FormatError(f"name {value!r} is longer than {n - 1} bytes")
        self.parts.append(raw.ljust(n, b"\0"))

    def getvalue(self) -> bytes:
        return b"".join(self.parts)


# ---- field specs -----------------------------------------------------------------------------------------------
def _read_fields(r: Reader, spec) -> dict:
    out = {}
    for name, kind in spec:
        if kind.startswith("s"):
            out[name] = r.text(int(kind[1:]))
        elif kind[0].isdigit():
            out[name] = list(r.unpack(kind))
        else:
            out[name] = r.unpack(kind)[0]
    return out


def _write_fields(w: Writer, obj: dict, spec) -> None:
    for name, kind in spec:
        if kind.startswith("s"):
            w.text(obj[name], int(kind[1:]))
        elif kind[0].isdigit():
            w.pack(kind, *obj[name])
        else:
            w.pack(kind, obj[name])


def _read_extent(r: Reader) -> dict:
    return _read_fields(r, EXTENT)


def _write_extent(w: Writer, e: dict) -> None:
    _write_fields(w, e, EXTENT)


# ---- tracks ----------------------------------------------------------------------------------------------------
def _read_track(r: Reader, tag: str) -> dict:
    kind = TRACKS.get(tag)
    if kind is None:
        raise FormatError(f"unknown MDX animation track {tag!r} at offset {r.pos - 4}")
    count, interpolation, global_sequence = r.unpack("IIi")
    fmt = "I" if kind == "u" else f"{kind}f"
    keys = []
    for _ in range(count):
        frame = r.unpack("i")[0]
        value = list(r.unpack(fmt))
        if interpolation > 1:
            keys.append([frame, value, list(r.unpack(fmt)), list(r.unpack(fmt))])
        else:
            keys.append([frame, value])
    return {"tag": tag, "interpolation": interpolation, "global_sequence": global_sequence, "keys": keys}


def _write_track(w: Writer, t: dict) -> None:
    kind = TRACKS[t["tag"]]
    fmt = "I" if kind == "u" else f"{kind}f"
    w.raw(t["tag"].encode("latin-1"))
    w.pack("IIi", len(t["keys"]), t["interpolation"], t["global_sequence"])
    for key in t["keys"]:
        w.pack("i", key[0])
        w.pack(fmt, *key[1])
        if t["interpolation"] > 1:
            w.pack(fmt, *key[2])
            w.pack(fmt, *key[3])


def _read_tracks(r: Reader, end: int) -> list[dict]:
    tracks = []
    while r.pos < end:
        tracks.append(_read_track(r, r.tag()))
    if r.pos != end:
        raise FormatError(f"MDX animation tracks overrun their object at offset {r.pos}")
    return tracks


def _write_tracks(w: Writer, tracks: list[dict]) -> None:
    for t in tracks:
        _write_track(w, t)


def _sized(w_body: Writer, include_size: bool = True) -> bytes:
    body = w_body.getvalue()
    return struct.pack("<I", len(body) + 4) + body if include_size else body


# ---- generic objects (nodes) -----------------------------------------------------------------------------------
NODE = (("name", "s80"), ("object_id", "I"), ("parent_id", "I"), ("flags", "I"))


def _read_node(r: Reader) -> dict:
    start = r.pos
    size = r.u32()
    node = _read_fields(r, NODE)
    node["tracks"] = _read_tracks(r, start + size)
    return node


def _write_node(w: Writer, node: dict) -> None:
    body = Writer()
    _write_fields(body, node, NODE)
    _write_tracks(body, node["tracks"])
    w.raw(_sized(body))


def _read_inclusive(r: Reader, read_body) -> dict:
    start = r.pos
    size = r.u32()
    obj = read_body(r, start + size)
    if r.pos != start + size:
        raise FormatError(f"MDX object at offset {start} has {start + size - r.pos} unread bytes")
    return obj


# ---- chunk readers and writers ---------------------------------------------------------------------------------
SEQUENCE = (("name", "s80"), ("interval", "2I"), ("move_speed", "f"), ("flags", "I"), ("rarity", "f"),
            ("sync_point", "I")) + EXTENT
TEXTURE = (("replaceable_id", "I"), ("path", "s260"), ("flags", "I"))
FACE_EFFECT = (("type", "s80"), ("path", "s260"))


class _Chunks:
    def __init__(self, version: int):
        self.version = version
        self.skin = "H" if version >= 1600 else "B"   # bone indices and weights: 8 bytes per vertex, 16-bit in 1600+

    # fixed-size lists
    def read_list(self, r: Reader, end: int, spec):
        items = []
        while r.pos < end:
            items.append(_read_fields(r, spec))
        return items

    def write_list(self, w: Writer, items, spec):
        for item in items:
            _write_fields(w, item, spec)

    # materials
    def read_material(self, r: Reader, end: int) -> dict:
        m = {"priority_plane": r.unpack("i")[0], "flags": r.u32()}
        if 800 < self.version < 1100:
            m["shader"] = r.text(80)
        if r.tag() != "LAYS":
            raise FormatError(f"material without LAYS at offset {r.pos - 4}")
        m["layers"] = [_read_inclusive(r, self.read_layer) for _ in range(r.u32())]
        return m

    def read_layer(self, r: Reader, end: int) -> dict:
        layer = _read_fields(r, (("filter_mode", "I"), ("flags", "I"), ("texture_id", "I"), ("texture_animation_id", "I"),
                                 ("coord_id", "I"), ("alpha", "f")))
        if self.version > 800:
            layer["emissive_gain"] = r.unpack("f")[0]
        if self.version > 900:
            layer.update(_read_fields(r, (("fresnel_color", "3f"), ("fresnel_opacity", "f"), ("fresnel_team_color", "f"))))
        if self.version > 1000:
            layer["hd"] = r.u32()
            textures = []
            for _ in range(r.u32()):
                texture = {"texture_id": r.u32(), "semantic": r.u32()}
                texture["tracks"] = [_read_track(r, r.tag())] if r.peek_tag() == "KMTF" else []
                textures.append(texture)
            layer["textures"] = textures
        layer["tracks"] = _read_tracks(r, end)
        return layer

    def write_material(self, w: Writer, m: dict) -> None:
        body = Writer()
        body.pack("iI", m["priority_plane"], m["flags"])
        if 800 < self.version < 1100:
            body.text(m["shader"], 80)
        body.raw(b"LAYS")
        body.pack("I", len(m["layers"]))
        for layer in m["layers"]:
            lw = Writer()
            _write_fields(lw, layer, (("filter_mode", "I"), ("flags", "I"), ("texture_id", "I"),
                                      ("texture_animation_id", "I"), ("coord_id", "I"), ("alpha", "f")))
            if self.version > 800:
                lw.pack("f", layer["emissive_gain"])
            if self.version > 900:
                _write_fields(lw, layer, (("fresnel_color", "3f"), ("fresnel_opacity", "f"), ("fresnel_team_color", "f")))
            if self.version > 1000:
                lw.pack("II", layer["hd"], len(layer["textures"]))
                for texture in layer["textures"]:
                    lw.pack("II", texture["texture_id"], texture["semantic"])
                    _write_tracks(lw, texture["tracks"])
            _write_tracks(lw, layer["tracks"])
            body.raw(_sized(lw))
        w.raw(_sized(body))

    # geosets
    ARRAYS = (("VRTX", "vertices", "3f"), ("NRMS", "normals", "3f"), ("PTYP", "face_types", "I"),
              ("PCNT", "face_groups", "I"), ("PVTX", "faces", "H"), ("GNDX", "vertex_groups", "B"),
              ("MTGC", "matrix_groups", "I"), ("MATS", "matrix_indices", "I"))

    def _array(self, r: Reader, tag: str, fmt: str):
        found = r.tag()
        if found != tag:
            raise FormatError(f"geoset expected {tag}, found {found!r} at offset {r.pos - 4}")
        count = r.u32()
        n = int(fmt[0]) if fmt[0].isdigit() else 1
        return list(r.unpack(f"{count * n}{fmt[-1]}"))

    def read_geoset(self, r: Reader, end: int) -> dict:
        g = {key: self._array(r, tag, fmt) for tag, key, fmt in self.ARRAYS}
        g.update(_read_fields(r, (("material_id", "I"), ("selection_group", "I"), ("selection_flags", "I"))))
        if self.version > 800:
            g["lod"], g["lod_name"] = r.u32(), r.text(80)
        g["extent"] = _read_extent(r)
        g["sequence_extents"] = [_read_extent(r) for _ in range(r.u32())]
        if self.version > 800:
            for tag, key, fmt in (("TANG", "tangents", "4f"), ("SKIN", "skin", self.skin)):
                if r.peek_tag() == tag:
                    g[key] = self._array(r, tag, fmt)
        if r.tag() != "UVAS":
            raise FormatError(f"geoset without UVAS at offset {r.pos - 4}")
        g["uvs"] = [self._array(r, "UVBS", "2f") for _ in range(r.u32())]
        return g

    def write_geoset(self, w: Writer, g: dict) -> None:
        body = Writer()

        def array(tag, values, fmt):
            n = int(fmt[0]) if fmt[0].isdigit() else 1
            body.raw(tag.encode())
            body.pack("I", len(values) // n)
            body.pack(f"{len(values)}{fmt[-1]}", *values)

        for tag, key, fmt in self.ARRAYS:
            array(tag, g[key], fmt)
        _write_fields(body, g, (("material_id", "I"), ("selection_group", "I"), ("selection_flags", "I")))
        if self.version > 800:
            body.pack("I", g["lod"])
            body.text(g["lod_name"], 80)
        _write_extent(body, g["extent"])
        body.pack("I", len(g["sequence_extents"]))
        for e in g["sequence_extents"]:
            _write_extent(body, e)
        if self.version > 800:
            for tag, key, fmt in (("TANG", "tangents", "4f"), ("SKIN", "skin", self.skin)):
                if key in g:
                    array(tag, g[key], fmt)
        body.raw(b"UVAS")
        body.pack("I", len(g["uvs"]))
        for uv in g["uvs"]:
            array("UVBS", uv, "2f")
        w.raw(_sized(body))

    # geoset animations
    GEOSET_ANIMATION = (("alpha", "f"), ("flags", "I"), ("color", "3f"), ("geoset_id", "I"))

    def read_geoset_animation(self, r: Reader, end: int) -> dict:
        a = _read_fields(r, self.GEOSET_ANIMATION)
        a["tracks"] = _read_tracks(r, end)
        return a

    def write_geoset_animation(self, w: Writer, a: dict) -> None:
        body = Writer()
        _write_fields(body, a, self.GEOSET_ANIMATION)
        _write_tracks(body, a["tracks"])
        w.raw(_sized(body))

    # nodes
    def read_bone(self, r: Reader) -> dict:
        bone = _read_node(r)
        bone.update(_read_fields(r, (("geoset_id", "I"), ("geoset_animation_id", "I"))))
        return bone

    def write_bone(self, w: Writer, bone: dict) -> None:
        _write_node(w, bone)
        _write_fields(w, bone, (("geoset_id", "I"), ("geoset_animation_id", "I")))

    def _read_node_object(self, spec, extra=None):
        def read(r: Reader, end: int) -> dict:
            obj = {"node": _read_node(r)}
            obj.update(_read_fields(r, spec))
            if extra:
                extra(r, obj)
            obj["tracks"] = _read_tracks(r, end)
            return obj
        return read

    def _write_node_object(self, w: Writer, obj: dict, spec, extra=None) -> None:
        body = Writer()
        _write_node(body, obj["node"])
        _write_fields(body, obj, spec)
        if extra:
            extra(body, obj)
        _write_tracks(body, obj["tracks"])
        w.raw(_sized(body))

    LIGHT = (("type", "I"), ("attenuation", "2f"), ("color", "3f"), ("intensity", "f"), ("ambient_color", "3f"),
             ("ambient_intensity", "f"))
    # 1600+ adds a value after the type and six after the ambient intensity (their meaning is not documented)
    LIGHT_1600 = (("type", "I"), ("unknown_1", "I"), ("attenuation", "2f"), ("color", "3f"), ("intensity", "f"),
                  ("ambient_color", "3f"), ("ambient_intensity", "f"), ("unknown_2", "6f"))
    ATTACHMENT = (("path", "s260"), ("attachment_id", "I"))
    EMITTER = (("emission_rate", "f"), ("gravity", "f"), ("longitude", "f"), ("latitude", "f"), ("path", "s260"),
               ("lifespan", "f"), ("speed", "f"))
    EMITTER2 = (("speed", "f"), ("variation", "f"), ("latitude", "f"), ("gravity", "f"), ("lifespan", "f"),
                ("emission_rate", "f"), ("width", "f"), ("length", "f"), ("filter_mode", "I"), ("rows", "I"),
                ("columns", "I"), ("head_or_tail", "I"), ("tail_length", "f"), ("time", "f"), ("segment_color", "9f"),
                ("segment_alpha", "3B"), ("segment_scaling", "3f"), ("head_intervals", "6I"), ("tail_intervals", "6I"),
                ("texture_id", "I"), ("squirt", "I"), ("priority_plane", "i"), ("replaceable_id", "I"))
    RIBBON = (("height_above", "f"), ("height_below", "f"), ("alpha", "f"), ("color", "3f"), ("lifespan", "f"),
              ("texture_slot", "I"), ("emission_rate", "I"), ("rows", "I"), ("columns", "I"), ("material_id", "I"),
              ("gravity", "f"))
    CORN = (("lifespan", "f"), ("emission_rate", "f"), ("speed", "f"), ("color", "3f"), ("alpha", "f"),
            ("replaceable_id", "I"), ("path", "s260"), ("animation_visibility_guide", "s260"))
    CAMERA = (("name", "s80"), ("position", "3f"), ("field_of_view", "f"), ("far_clipping_plane", "f"),
              ("near_clipping_plane", "f"), ("target_position", "3f"))

    def read_camera(self, r: Reader) -> dict:
        start, value = r.pos, r.u32()
        c = {"size_flags": value >> 24}   # the game's cameras keep 3 in the top byte of their size
        c.update(_read_fields(r, self.CAMERA))
        c["tracks"] = _read_tracks(r, start + (value & 0xFFFFFF))
        return c

    def write_camera(self, w: Writer, c: dict) -> None:
        body = Writer()
        _write_fields(body, c, self.CAMERA)
        _write_tracks(body, c["tracks"])
        data = body.getvalue()
        w.pack("I", (len(data) + 4) | c.get("size_flags", 0) << 24)
        w.raw(data)

    def read_event(self, r: Reader) -> dict:
        e = {"node": _read_node(r)}
        if r.peek_tag() == "KEVT":
            r.take(4)
            count = r.u32()
            e["global_sequence"] = r.unpack("i")[0]
            e["frames"] = list(r.unpack(f"{count}I"))
        return e

    def write_event(self, w: Writer, e: dict) -> None:
        _write_node(w, e["node"])
        if "frames" in e:
            w.raw(b"KEVT")
            w.pack("Ii", len(e["frames"]), e["global_sequence"])
            w.pack(f"{len(e['frames'])}I", *e["frames"])

    def read_collision(self, r: Reader) -> dict:
        c = {"node": _read_node(r), "type": r.u32()}
        c["vertices"] = list(r.unpack("3f" if c["type"] == 2 else "6f"))   # box, plane, sphere, cylinder
        if c["type"] in (2, 3):
            c["radius"] = r.unpack("f")[0]
        return c

    def write_collision(self, w: Writer, c: dict) -> None:
        _write_node(w, c["node"])
        w.pack("I", c["type"])
        w.pack(f"{len(c['vertices'])}f", *c["vertices"])
        if "radius" in c:
            w.pack("f", c["radius"])


def _chunk_spec(ch: _Chunks):
    """tag -> (key, reader(r, end) -> items, writer(w, items))"""
    def inclusive_list(read, write):
        return (lambda r, end: [_read_inclusive(r, read) for _ in iter(lambda: r.pos < end, False)],
                lambda w, items: [write(w, x) for x in items])

    def plain_list(read, write):
        return (lambda r, end: [read(r) for _ in iter(lambda: r.pos < end, False)],
                lambda w, items: [write(w, x) for x in items])

    def node_list(spec, extra_read=None, extra_write=None):
        return inclusive_list(ch._read_node_object(spec, extra_read),
                              lambda w, x: ch._write_node_object(w, x, spec, extra_write))

    return {
        "MODL": ("info", lambda r, end: _read_fields(r, (("name", "s80"), ("animation_file", "s260")) + EXTENT
                                                     + (("blend_time", "I"),)),
                 lambda w, x: _write_fields(w, x, (("name", "s80"), ("animation_file", "s260")) + EXTENT
                                            + (("blend_time", "I"),))),
        "SEQS": ("sequences", lambda r, end: ch.read_list(r, end, SEQUENCE), lambda w, x: ch.write_list(w, x, SEQUENCE)),
        "GLBS": ("global_sequences", lambda r, end: list(r.unpack(f"{(end - r.pos) // 4}I")),
                 lambda w, x: w.pack(f"{len(x)}I", *x)),
        "TEXS": ("textures", lambda r, end: ch.read_list(r, end, TEXTURE), lambda w, x: ch.write_list(w, x, TEXTURE)),
        "MTLS": ("materials",) + inclusive_list(ch.read_material, ch.write_material),
        "TXAN": ("texture_animations",) + inclusive_list(lambda r, end: {"tracks": _read_tracks(r, end)},
                                                         lambda w, x: w.raw(_sized(_tracks_writer(x["tracks"])))),
        "GEOS": ("geosets",) + inclusive_list(ch.read_geoset, ch.write_geoset),
        "GEOA": ("geoset_animations",) + inclusive_list(ch.read_geoset_animation, ch.write_geoset_animation),
        "BONE": ("bones",) + plain_list(ch.read_bone, ch.write_bone),
        "LITE": ("lights",) + node_list(ch.LIGHT_1600 if ch.version >= 1600 else ch.LIGHT),
        "HELP": ("helpers",) + plain_list(_read_node, _write_node),
        "ATCH": ("attachments",) + node_list(ch.ATTACHMENT),
        "PIVT": ("pivots", lambda r, end: [list(r.unpack("3f")) for _ in range((end - r.pos) // 12)],
                 lambda w, x: [w.pack("3f", *p) for p in x]),
        "PREM": ("particle_emitters",) + node_list(ch.EMITTER),
        "PRE2": ("particle_emitters2",) + node_list(ch.EMITTER2),
        "RIBB": ("ribbon_emitters",) + node_list(ch.RIBBON),
        "CAMS": ("cameras",) + plain_list(ch.read_camera, ch.write_camera),
        "EVTS": ("event_objects",) + plain_list(ch.read_event, ch.write_event),
        "CLID": ("collision_shapes",) + plain_list(ch.read_collision, ch.write_collision),
        "CORN": ("corn_emitters",) + node_list(ch.CORN),
        "FAFX": ("face_effects", lambda r, end: ch.read_list(r, end, FACE_EFFECT),
                 lambda w, x: ch.write_list(w, x, FACE_EFFECT)),
        "BPOS": ("bind_poses", lambda r, end: [list(r.unpack("12f")) for _ in range(r.u32())],
                 lambda w, x: (w.pack("I", len(x)), [w.pack("12f", *m) for m in x])),
    }


def _tracks_writer(tracks) -> Writer:
    w = Writer()
    _write_tracks(w, tracks)
    return w


def parse(data: bytes) -> dict:
    """{"version", "chunks": [[tag, value], ...]} with values as described in the module docstring; unknown chunks
    keep their raw bytes."""
    if data[:4] != MAGIC:
        raise FormatError("not an MDX model (no MDLX header)")
    r = Reader(data, 4)
    if r.tag() != "VERS" or r.u32() != 4:
        raise FormatError("MDX model does not start with a version chunk")
    version = r.u32()
    specs = _chunk_spec(_Chunks(version))
    chunks = []
    while r.pos < len(data):
        tag, size = r.tag(), r.u32()
        end = r.pos + size
        if end > len(data):
            raise FormatError(f"MDX chunk {tag!r} runs past the end of the file")
        if tag in specs:
            sub = Reader(data, r.pos, end)
            try:
                value = specs[tag][1](sub, end)
            except FormatError as e:
                raise FormatError(f"MDX chunk {tag}: {e}") from e
            if sub.pos != end:
                raise FormatError(f"MDX chunk {tag} has {end - sub.pos} unread bytes (version {version})")
        else:
            value = data[r.pos:end]
        chunks.append([tag, value])
        r.pos = end
    return {"version": version, "chunks": chunks}


def serialize(model: dict) -> bytes:
    specs = _chunk_spec(_Chunks(model["version"]))
    w = Writer()
    w.raw(MAGIC + b"VERS" + struct.pack("<II", 4, model["version"]))
    for tag, value in model["chunks"]:
        body = Writer()
        if isinstance(value, bytes):
            body.raw(value)
        else:
            specs[tag][2](body, value)
        payload = body.getvalue()
        w.raw(tag.encode("latin-1") + struct.pack("<I", len(payload)) + payload)
    return w.getvalue()


def chunk(model: dict, tag: str, default=None):
    return next((value for t, value in model["chunks"] if t == tag), default)
