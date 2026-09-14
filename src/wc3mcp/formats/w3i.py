"""war3map.w3i — map info. Reads format versions 25-39; byte-exact on local v31/v33/v39 maps. The v39 additions
were derived from Warcraft III 3.0.0.24268 campaign maps; their meaning is not documented."""
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

WRITABLE_VERSIONS = frozenset({31, 33, 39})
PLAYER_FLAG_V39_EXTRA = 0x40  # v39: the player record has one extra i32 after its flags when this bit is set


@dataclass
class Player:
    id: int
    controller: int
    race: int
    flags: int
    name: str
    start_x: float
    start_y: float
    ally_low: int
    ally_high: int
    enemy_low: int = 0
    enemy_high: int = 0
    v39_value: int = 1


@dataclass
class Force:
    flags: int
    players: int
    name: str


@dataclass
class UpgradeChange:
    players: int
    id: bytes
    level: int
    availability: int


@dataclass
class TechChange:
    players: int
    id: bytes


@dataclass
class RandomUnitTable:
    id: int
    name: str
    positions: list[int]
    lines: list[tuple[int, list[bytes]]]


@dataclass
class RandomItemTable:
    id: int
    name: str
    sets: list[list[tuple[int, bytes]]]


@dataclass
class MapInfo:
    version: int
    map_version: int = 0
    editor_version: int = 0
    game_version: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    name: str = ""
    author: str = ""
    description: str = ""
    players_recommended: str = ""
    camera_bounds: list[float] = field(default_factory=lambda: [0.0] * 8)
    camera_complements: list[int] = field(default_factory=lambda: [0] * 4)
    playable_width: int = 0
    playable_height: int = 0
    flags: int = 0
    tileset: int = ord("L")
    loading_screen_background: int = -1
    loading_screen_model: str = ""
    loading_screen_text: str = ""
    loading_screen_title: str = ""
    loading_screen_subtitle: str = ""
    game_data_set: int = 0
    prologue_path: str = ""
    prologue_text: str = ""
    prologue_title: str = ""
    prologue_subtitle: str = ""
    fog_style: int = 0
    fog_start_z: float = 0.0
    fog_end_z: float = 0.0
    fog_density: float = 0.0
    fog_color: bytes = b"\0\0\0\xff"
    global_weather: bytes = b"\0\0\0\0"
    sound_environment: str = ""
    light_environment: int = 0
    water_tint: bytes = b"\xff\xff\xff\xff"
    script_language: int = 0
    supported_modes: int = 3
    game_data_version: int = 1
    default_camera_zoom: int = 0
    max_camera_zoom: int = 0
    min_camera_zoom: int = 0
    v39_after_loading_background: int = 1
    v39_after_weather: list[int] = field(default_factory=lambda: [0, 0x461C4000, 0x461C4000, 0x3F800000, 0, 0])
    v39_after_zoom: list[int] = field(default_factory=lambda: [0, 100, 10, 0, 10, 20, 100, 0, 100, -1])
    players: list[Player] = field(default_factory=list)
    forces: list[Force] = field(default_factory=list)
    upgrades: list[UpgradeChange] = field(default_factory=list)
    tech: list[TechChange] = field(default_factory=list)
    random_unit_tables: list[RandomUnitTable] = field(default_factory=list)
    random_item_tables: list[RandomItemTable] = field(default_factory=list)
    truncated: bool = False  # protected maps end with byte 255 right after the forces
    trailing: bytes = b""


def parse(data: bytes) -> MapInfo:
    r = Reader(data)
    v = r.i32()
    if not 25 <= v <= 39:
        raise FormatError(f"unsupported w3i format version {v}")
    mi = MapInfo(v, map_version=r.i32(), editor_version=r.i32())
    if v >= 27:
        mi.game_version = [r.i32() for _ in range(4)]
    mi.name, mi.author, mi.description, mi.players_recommended = r.cstr(), r.cstr(), r.cstr(), r.cstr()
    mi.camera_bounds = [r.f32() for _ in range(8)]
    mi.camera_complements = [r.i32() for _ in range(4)]
    mi.playable_width, mi.playable_height, mi.flags, mi.tileset = r.i32(), r.i32(), r.u32(), r.u8()
    mi.loading_screen_background = r.i32()
    if v >= 39:
        mi.v39_after_loading_background = r.i32()
    mi.loading_screen_model, mi.loading_screen_text = r.cstr(), r.cstr()
    mi.loading_screen_title, mi.loading_screen_subtitle = r.cstr(), r.cstr()
    mi.game_data_set = r.i32()
    mi.prologue_path, mi.prologue_text, mi.prologue_title, mi.prologue_subtitle = r.cstr(), r.cstr(), r.cstr(), r.cstr()
    mi.fog_style, mi.fog_start_z, mi.fog_end_z, mi.fog_density = r.i32(), r.f32(), r.f32(), r.f32()
    mi.fog_color, mi.global_weather = r.raw(4), r.raw(4)
    if v >= 39:
        mi.v39_after_weather = [r.u32() for _ in range(6)]
    mi.sound_environment, mi.light_environment, mi.water_tint = r.cstr(), r.u8(), r.raw(4)
    if v >= 28:
        mi.script_language = r.i32()
    if v >= 31:
        mi.supported_modes, mi.game_data_version = r.i32(), r.i32()
    if v >= 32:
        mi.default_camera_zoom, mi.max_camera_zoom = r.i32(), r.i32()
    if v >= 33:
        mi.min_camera_zoom = r.i32()
    if v >= 39:
        mi.v39_after_zoom = [r.i32() for _ in range(10)]
    for _ in range(r.count(item_size=33)):
        p = Player(r.i32(), r.i32(), r.i32(), r.u32(), "", 0.0, 0.0, 0, 0)
        if v >= 39 and p.flags & PLAYER_FLAG_V39_EXTRA:
            p.v39_value = r.i32()
        p.name, p.start_x, p.start_y, p.ally_low, p.ally_high = r.cstr(), r.f32(), r.f32(), r.u32(), r.u32()
        if v >= 31:
            p.enemy_low, p.enemy_high = r.u32(), r.u32()
        mi.players.append(p)
    for _ in range(r.count(item_size=9)):
        mi.forces.append(Force(r.u32(), r.u32(), r.cstr()))
    if r.peek_u8() == 255:  # War3Net treats this as "skip the rest"
        r.u8()
        mi.truncated, mi.trailing = True, r.rest()
        return mi
    for _ in range(r.count(item_size=16)):
        mi.upgrades.append(UpgradeChange(r.u32(), r.raw(4), r.i32(), r.i32()))
    for _ in range(r.count(item_size=8)):
        mi.tech.append(TechChange(r.u32(), r.raw(4)))
    for _ in range(r.count(item_size=13)):
        tid, tname = r.i32(), r.cstr()
        positions = [r.i32() for _ in range(r.count(item_size=4))]
        lines = [(r.i32(), [r.raw(4) for _ in positions]) for _ in range(r.count(item_size=4 * (len(positions) + 1)))]
        mi.random_unit_tables.append(RandomUnitTable(tid, tname, positions, lines))
    for _ in range(r.count(item_size=9)):
        tid, tname = r.i32(), r.cstr()
        sets = [[(r.i32(), r.raw(4)) for _ in range(r.count(item_size=8))] for _ in range(r.count(item_size=4))]
        mi.random_item_tables.append(RandomItemTable(tid, tname, sets))
    if 26 <= v < 28:
        r.i32()  # always 0
    mi.trailing = r.rest()
    return mi


def _four(b: bytes, what: str) -> bytes:
    if len(b) != 4:
        raise FormatError(f"{what} must be exactly 4 bytes")
    return b


def serialize(mi: MapInfo) -> bytes:
    w, v = Writer(), mi.version
    w.i32(v)
    w.i32(mi.map_version)
    w.i32(mi.editor_version)
    if v >= 27:
        for x in mi.game_version:
            w.i32(x)
    for s in (mi.name, mi.author, mi.description, mi.players_recommended):
        w.cstr(s)
    for f in mi.camera_bounds:
        w.f32(f)
    for c in mi.camera_complements:
        w.i32(c)
    w.i32(mi.playable_width)
    w.i32(mi.playable_height)
    w.u32(mi.flags)
    w.u8(mi.tileset)
    w.i32(mi.loading_screen_background)
    if v >= 39:
        w.i32(mi.v39_after_loading_background)
    for s in (mi.loading_screen_model, mi.loading_screen_text, mi.loading_screen_title, mi.loading_screen_subtitle):
        w.cstr(s)
    w.i32(mi.game_data_set)
    for s in (mi.prologue_path, mi.prologue_text, mi.prologue_title, mi.prologue_subtitle):
        w.cstr(s)
    w.i32(mi.fog_style)
    w.f32(mi.fog_start_z)
    w.f32(mi.fog_end_z)
    w.f32(mi.fog_density)
    w.raw(_four(mi.fog_color, "fog color"))
    w.raw(_four(mi.global_weather, "global weather"))
    if v >= 39:
        for x in mi.v39_after_weather:
            w.u32(x)
    w.cstr(mi.sound_environment)
    w.u8(mi.light_environment)
    w.raw(_four(mi.water_tint, "water tint"))
    if v >= 28:
        w.i32(mi.script_language)
    if v >= 31:
        w.i32(mi.supported_modes)
        w.i32(mi.game_data_version)
    if v >= 32:
        w.i32(mi.default_camera_zoom)
        w.i32(mi.max_camera_zoom)
    if v >= 33:
        w.i32(mi.min_camera_zoom)
    if v >= 39:
        for x in mi.v39_after_zoom:
            w.i32(x)
    w.i32(len(mi.players))
    for p in mi.players:
        w.i32(p.id)
        w.i32(p.controller)
        w.i32(p.race)
        w.u32(p.flags)
        if v >= 39 and p.flags & PLAYER_FLAG_V39_EXTRA:
            w.i32(p.v39_value)
        w.cstr(p.name)
        w.f32(p.start_x)
        w.f32(p.start_y)
        w.u32(p.ally_low)
        w.u32(p.ally_high)
        if v >= 31:
            w.u32(p.enemy_low)
            w.u32(p.enemy_high)
    w.i32(len(mi.forces))
    for f in mi.forces:
        w.u32(f.flags)
        w.u32(f.players)
        w.cstr(f.name)
    if mi.truncated:
        w.u8(255)
        w.raw(mi.trailing)
        return w.getvalue()
    w.i32(len(mi.upgrades))
    for u in mi.upgrades:
        w.u32(u.players)
        w.raw(_four(u.id, "upgrade id"))
        w.i32(u.level)
        w.i32(u.availability)
    w.i32(len(mi.tech))
    for t in mi.tech:
        w.u32(t.players)
        w.raw(_four(t.id, "tech id"))
    w.i32(len(mi.random_unit_tables))
    for table in mi.random_unit_tables:
        w.i32(table.id)
        w.cstr(table.name)
        w.i32(len(table.positions))
        for pos in table.positions:
            w.i32(pos)
        w.i32(len(table.lines))
        for chance, ids in table.lines:
            if len(ids) != len(table.positions):
                raise FormatError(f"random unit table {table.id}: each line needs one id per position")
            w.i32(chance)
            for rawcode in ids:
                w.raw(_four(rawcode, "random unit id"))
    w.i32(len(mi.random_item_tables))
    for table in mi.random_item_tables:
        w.i32(table.id)
        w.cstr(table.name)
        w.i32(len(table.sets))
        for item_set in table.sets:
            w.i32(len(item_set))
            for chance, rawcode in item_set:
                w.i32(chance)
                w.raw(_four(rawcode, "random item id"))
    if 26 <= v < 28:
        w.i32(0)
    w.raw(mi.trailing)
    return w.getvalue()
