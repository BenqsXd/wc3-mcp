"""*.w3g — replays. Reads the v1 header (Reforged blocks carry a 12-byte block header, classic ones 8), the game
info (host, map, players, slots) and the replay stream: time slots with each player's actions, chat and leaves.
Action lengths up to 0x6B are the documented 1.07+ ones; the Reforged ids 0x75-0x7A were measured on local 2.0
replays (build 7000). An action id this reader does not know ends that player's block for that time slot: it is
counted in `unknown` and parsing goes on with the next block, so one surprise never loses the rest of the game."""
import math
import struct
import zlib
from dataclasses import dataclass, field

from .binary import FormatError, Reader

MAGIC = b"Warcraft III recorded game\x1a\0"

# action id -> (name, fixed payload length); None = variable, parsed in _action
ACTIONS: dict[int, tuple[str, int | None]] = {
    0x01: ("pause", 0), 0x02: ("resume", 0), 0x03: ("set_speed", 1), 0x04: ("speed_up", 0), 0x05: ("speed_down", 0),
    0x06: ("save_game", None), 0x07: ("save_done", 4),
    0x10: ("order", 14), 0x11: ("order_point", 22), 0x12: ("order_target", 30), 0x13: ("give_item", 38),
    0x14: ("order_two_points", 43),
    0x16: ("select", None), 0x17: ("hotkey_assign", None), 0x18: ("hotkey_select", 2), 0x19: ("subgroup", 12),
    0x1A: ("pre_subselect", 0), 0x1B: ("unknown_1b", 9), 0x1C: ("select_item", 9), 0x1D: ("cancel_revive", 8),
    0x1E: ("dequeue", 5), 0x21: ("unknown_21", 8),
    0x20: ("cheat", 0), 0x22: ("cheat", 0), 0x23: ("cheat", 0), 0x24: ("cheat", 0), 0x25: ("cheat", 0),
    0x26: ("cheat", 0), 0x27: ("cheat", 5), 0x28: ("cheat", 5), 0x29: ("cheat", 0), 0x2A: ("cheat", 0),
    0x2B: ("cheat", 0), 0x2C: ("cheat", 0), 0x2D: ("cheat", 5), 0x2E: ("cheat", 4), 0x2F: ("cheat", 0),
    0x30: ("cheat", 0), 0x31: ("cheat", 0), 0x32: ("cheat", 0),
    0x50: ("ally_options", 5), 0x51: ("transfer", 9),
    0x60: ("trigger_chat", None), 0x61: ("esc", 0), 0x62: ("trigger_sync", 12), 0x66: ("hero_skill_menu", 0),
    0x67: ("build_menu", 0), 0x68: ("ping", 12), 0x69: ("continue", 16), 0x6A: ("continue", 16),
    0x6B: ("sync_stored", None),
    # Reforged, measured on 2.0 replays: 0x76 mouse event, x, y, button; 0x7A unit, ability, order (the command card
    # click that comes before its 0x10-0x14 order); 0x78 and 0x79 unknown, fixed lengths 17 and 20 (0x79 names a unit)
    0x75: ("arrow_key", 1), 0x76: ("mouse", 10), 0x78: ("unknown_78", 17), 0x79: ("unknown_79", 20),
    0x7A: ("command", 16),
}
ORDER_ACTIONS = frozenset({0x10, 0x11, 0x12, 0x13, 0x14})
NONE32 = 0xFFFFFFFF
# game base orders (851971 = 0xD0003 ...): the ones a replay is full of; ability orders come from orderids.json
BASE_ORDERS = {851971: "smart", 851972: "stop", 851976: "cancel", 851980: "setrally", 851981: "getitem",
               851983: "attack", 851984: "attackground", 851985: "attackonce", 851986: "move", 851990: "patrol",
               851993: "holdposition",
               **{852002 + i: f"moveslot{i + 1}" for i in range(6)}, **{852008 + i: f"useslot{i + 1}" for i in range(6)}}
CHAT_MODES = {0: "all", 1: "allies", 2: "observers"}
LEAVE_RESULTS = {0x01: "disconnect", 0x07: "left", 0x08: "lost", 0x09: "won", 0x0A: "draw", 0x0B: "observer_left"}
RACES = {0x01: "human", 0x02: "orc", 0x04: "nightelf", 0x08: "undead", 0x20: "random"}
SLOT_STATUS = {0: "empty", 1: "closed", 2: "used"}


@dataclass
class Replay:
    header: dict
    game: dict = field(default_factory=dict)
    players: dict[int, str] = field(default_factory=dict)     # player id -> name
    slots: list[dict] = field(default_factory=list)
    chat: list[dict] = field(default_factory=list)
    leaves: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    unknown: dict[str, int] = field(default_factory=dict)     # "0x7b" -> player blocks cut short by that action id
    end: dict = field(default_factory=dict)                   # where the stream stopped and why


def fourcc(value: int) -> str | None:
    """An id the game stores as a little-endian int ('AHbz' is read as 0x4148627A); None when it is not text."""
    raw = value.to_bytes(4, "big")
    return raw.decode("ascii") if all(0x20 < b < 0x7F for b in raw) else None


def ability(value: int, order_names: dict[int, str]) -> dict:
    """An order or ability id of an order action: FourCC text, or the numeric order id with its name when known."""
    code = fourcc(value)
    if code is not None:
        return {"id": code}
    return {"order_id": value, **({"order": order_names[value]} if value in order_names else {})}


def decompress(data: bytes) -> tuple[dict, bytes]:
    if not data.startswith(MAGIC) or len(data) < 64:
        raise FormatError("not a Warcraft III replay (no w3g header)")
    header_size, _, header_version, size, blocks = struct.unpack_from("<5I", data, 28)
    if header_version != 1:
        raise FormatError(f"unsupported replay header version {header_version} (only v1, patch 1.07 and later)")
    product, version, build, flags, length_ms = struct.unpack_from("<4sIHHI", data, 48)
    header = {"product": product[::-1].decode("latin-1"), "version": version, "build": build,
              "multiplayer": bool(flags & 0x8000), "length_ms": length_ms, "blocks": blocks}
    # Reforged (1.32, version 10032, and later): u32 compressed, u32 decompressed, u32 checksum per block; before: u16s
    layout = "<III" if version >= 10000 else "<HHI"
    step = struct.calcsize(layout)
    pos, out, read = header_size, bytearray(), 0
    while read < blocks and pos + step <= len(data):
        packed = struct.unpack_from(layout, data, pos)[0]
        pos += step
        try:   # blocks end in a sync flush, not a final block: decompressobj takes them as they are
            out += zlib.decompressobj().decompress(data[pos:pos + packed])
        except zlib.error as e:
            header["damaged_block"] = f"block {read}: {e}"
            break
        pos += packed
        read += 1
    header["blocks_read"] = read
    return header, bytes(out[:size])


def _decode_settings(encoded: bytes) -> bytes:
    """The game settings string: every 8th byte is a mask telling which of the next 7 bytes were stored +1."""
    out = bytearray()
    for i in range(0, len(encoded), 8):
        mask = encoded[i]
        for j, b in enumerate(encoded[i + 1:i + 8]):
            out.append(b if mask & (1 << (j + 1)) else b - 1)
    return bytes(out)


def _protobuf(data: bytes) -> list[tuple[int, int | bytes]]:
    """Top-level fields of a protobuf message: varints and length-delimited values (fixed ones skipped)."""
    out, pos = [], 0

    def varint() -> int:
        nonlocal pos
        value = shift = 0
        while True:
            b = data[pos]
            pos += 1
            value |= (b & 0x7F) << shift
            shift += 7
            if b < 0x80:
                return value
    try:
        while pos < len(data):
            key = varint()
            kind = key & 7
            if kind == 0:
                out.append((key >> 3, varint()))
            elif kind == 2:
                n = varint()
                out.append((key >> 3, data[pos:pos + n]))
                pos += n
            elif kind in (1, 5):
                pos += 8 if kind == 1 else 4
            else:
                break
    except IndexError:
        pass
    return out


def _game_info(r: Reader, rp: Replay) -> None:
    r.raw(4)
    if r.u8() != 0:
        raise FormatError("replay game info does not start with the host record")
    host = r.u8()
    rp.players[host] = r.cstr()
    r.raw(r.u8())
    rp.game["name"] = r.cstr()
    r.cstr()
    settings = _decode_settings(r.data[r.pos:r.data.index(b"\0", r.pos)])
    r.cstr()
    s = Reader(settings)
    speed = s.u8()
    s.raw(4)
    width, height = struct.unpack("<HH", s.raw(4))
    s.raw(4)
    rp.game.update({"speed": speed, "map_size": [width, height], "map": s.cstr(), "creator": s.cstr(),
                    "host_id": host, "slot_count": r.u32()})
    game_type = r.u8()
    rp.game["game_type"] = {0x01: "custom", 0x09: "custom", 0x20: "ladder"}.get(game_type, game_type)
    r.raw(7)   # private flag, unknown, language
    while r.peek_u8() == 0x16:
        r.u8()
        pid = r.u8()
        rp.players[pid] = r.cstr()
        r.raw(r.u8())
        r.raw(4)
    while r.peek_u8() == 0x38:   # Reforged: protobuf metadata; subtype 3 lists every lobby player (id 1, name 2)
        r.u8()
        subtype = r.u8()
        body = r.raw(r.u32())
        if subtype == 3:
            for number, entry in _protobuf(body):
                if number == 1 and isinstance(entry, bytes):
                    fields = dict(_protobuf(entry))
                    if isinstance(fields.get(1), int) and isinstance(fields.get(2), bytes):
                        rp.players[fields[1]] = fields[2].decode("utf-8", "replace")
    if r.u8() != 0x19:
        raise FormatError(f"replay game start record not found at offset {r.pos - 1}")
    size = struct.unpack("<H", r.raw(2))[0]
    body = Reader(r.raw(size))
    count = body.u8()
    width = (size - 7) // count if count else 0
    for _ in range(count):
        slot = body.raw(width)
        pid, _, status, computer, team, color, race = slot[:7]
        if status != 2:
            continue
        rp.slots.append({"player_id": pid, "team": team, "color": color, "computer": bool(computer),
                         "race": RACES.get(race & 0x2F, race), "status": SLOT_STATUS.get(status, status)})
    rp.game["random_seed"] = body.u32()


def _f(v: float) -> float | None:
    return round(v, 1) if math.isfinite(v) else None


def _obj(a: int, b: int) -> int | list[int] | None:
    """A unit or item as the replay names it: two handle-like ids, most often equal (then one number)."""
    return None if a == NONE32 and b == NONE32 else a if a == b else [a, b]


def _action(r: Reader, aid: int, order_names: dict[int, str]) -> dict:
    """One action's payload (the id already read) as a dict; `action` is its name."""
    name, size = ACTIONS[aid]
    row: dict = {"action": name}
    if size is not None:
        body = r.raw(size)
        if aid in ORDER_ACTIONS:
            flags, code = struct.unpack_from("<HI", body)
            row.update(ability(code, order_names), flags=flags)
            if aid >= 0x11:
                x, y = struct.unpack_from("<ff", body, 14)
                if _f(x) is not None and _f(y) is not None:
                    row["target"] = {"x": _f(x), "y": _f(y)}
            if aid in (0x12, 0x13):
                unit = _obj(*struct.unpack_from("<II", body, 22))
                if unit:
                    row.setdefault("target", {})["unit"] = unit
            if aid == 0x13:
                row["item"] = _obj(*struct.unpack_from("<II", body, 30))
            if aid == 0x14:
                code2, = struct.unpack_from("<I", body, 22)
                x2, y2 = struct.unpack_from("<ff", body, 35)
                row["second"] = {**ability(code2, order_names), "x": _f(x2), "y": _f(y2)}
        elif aid == 0x19:
            row.update(ability(struct.unpack_from("<I", body)[0], order_names))
        elif aid == 0x18:
            row["group"] = body[0]
        elif aid == 0x68:
            row.update(x=_f(struct.unpack_from("<f", body)[0]), y=_f(struct.unpack_from("<f", body, 4)[0]))
        elif aid == 0x51:
            row.update(slot=body[0], gold=struct.unpack_from("<I", body, 1)[0], lumber=struct.unpack_from("<I", body, 5)[0])
        elif aid == 0x76:
            row.update(event=body[0], x=_f(struct.unpack_from("<f", body, 1)[0]),
                       y=_f(struct.unpack_from("<f", body, 5)[0]), button=body[9])
        elif aid == 0x7A:
            row.update(unit=_obj(*struct.unpack_from("<II", body)), **ability(struct.unpack_from("<I", body, 8)[0],
                                                                                order_names),
                       then=ability(struct.unpack_from("<I", body, 12)[0], order_names))
        elif aid == 0x79:
            row.update(unit=_obj(*struct.unpack_from("<II", body)), raw=body[8:].hex())
        elif aid == 0x75:
            row["key"] = body[0]
        elif name.startswith("unknown"):
            row["raw"] = body.hex()
        return row
    if aid == 0x06:
        row["name"] = r.cstr()
    elif aid in (0x16, 0x17):
        mode = r.u8()
        n = struct.unpack("<H", r.raw(2))[0]
        r.raw(8 * n)
        row.update(mode=mode, units=n) if aid == 0x16 else row.update(group=mode, units=n)
    elif aid == 0x60:
        r.raw(8)
        row["text"] = r.cstr()
    elif aid == 0x6B:
        row.update(file=r.cstr(), group=r.cstr(), key=r.cstr(), value=r.u32())
    return row


class _Unknown(Exception):
    pass


def _block(block: bytes, pid: int, time: int, rp: Replay, order_names: dict[int, str]) -> None:
    r = Reader(block)
    while r.pos < len(block):
        aid = r.u8()
        if aid not in ACTIONS:
            key = f"0x{aid:02x}"
            rp.unknown[key] = rp.unknown.get(key, 0) + 1
            return
        try:
            row = _action(r, aid, order_names)
        except FormatError:
            key = f"0x{aid:02x}_short"
            rp.unknown[key] = rp.unknown.get(key, 0) + 1
            return
        rp.actions.append({"time_ms": time, "player_id": pid, **row})


def parse(data: bytes, order_names: dict[int, str] | None = None) -> Replay:
    header, stream = decompress(data)
    rp = Replay(header)
    names = {**BASE_ORDERS, **(order_names or {})}
    r = Reader(stream)
    _game_info(r, rp)
    time = 0
    while True:
        start = r.pos
        rec = r.peek_u8()
        try:
            if rec in (-1, 0):
                rp.end = {"reason": "end of data" if rec == -1 else "padding", "offset": start}
                break
            r.u8()
            if rec in (0x1A, 0x1B, 0x1C):
                r.raw(4)
            elif rec in (0x1E, 0x1F):
                size, step = struct.unpack("<HH", r.raw(4))
                body = r.raw(size - 2)
                time += step
                i = 0
                while i + 3 <= len(body):
                    pid, n = body[i], struct.unpack_from("<H", body, i + 1)[0]
                    _block(body[i + 3:i + 3 + n], pid, time, rp, names)
                    i += 3 + n
            elif rec == 0x20:
                pid = r.u8()
                size = struct.unpack("<H", r.raw(2))[0]
                body = Reader(r.raw(size))
                flags = body.u8()
                mode = body.u32() if flags == 0x20 else None
                rp.chat.append({"time_ms": time, "player_id": pid,
                                "to": "lobby" if mode is None else CHAT_MODES.get(mode, "private"),
                                "text": body.cstr()})
            elif rec == 0x22:
                r.raw(r.u8())
            elif rec == 0x23:
                r.raw(10)
            elif rec == 0x2F:
                r.raw(8)
            elif rec == 0x17:
                reason, pid, result, _ = struct.unpack("<IBII", r.raw(13))
                rp.leaves.append({"time_ms": time, "player_id": pid, "reason": reason,
                                  "result": LEAVE_RESULTS.get(result, result)})
            else:
                rp.end = {"reason": f"unknown record 0x{rec:02x}", "offset": start}
                break
        except FormatError:
            rp.end = {"reason": f"record 0x{rec:02x} cut short", "offset": start}
            break
    rp.end.update(time_ms=time, stream_bytes=len(stream))
    return rp
