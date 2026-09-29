import struct
import zlib

import pytest

from wc3mcp import config
from wc3mcp.formats import w3g
from wc3mcp.formats.binary import FormatError


def _encode_settings(raw: bytes) -> bytes:
    """The inverse of the replay's settings encoding: even bytes stored +1, a mask byte before every 7."""
    out = bytearray()
    for i in range(0, len(raw), 7):
        chunk, mask, stored = raw[i:i + 7], 1, bytearray()
        for j, b in enumerate(chunk):
            if b % 2:
                mask |= 1 << (j + 1)
                stored.append(b)
            else:
                stored.append(b + 1)
        out += bytes([mask]) + stored
    return bytes(out)


def _pb(number: int, value) -> bytes:
    if isinstance(value, int):
        return bytes([number << 3, value])
    return bytes([number << 3 | 2, len(value)]) + value


def _stream(actions: bytes, extra_records: bytes = b"") -> bytes:
    settings = bytes([2, 0, 0, 0, 0]) + struct.pack("<HH", 64, 96) + bytes(4) + b"Maps/Test.w3x\0Host\0\0"
    info = (bytes(4) + b"\0\x01Host\0\x01\0" + b"Game\0\0" + _encode_settings(settings) + b"\0"
            + struct.pack("<I", 12) + bytes([0x01, 0, 0, 0]) + bytes(4)
            + b"\x16\x02Guest\0\x01\0" + bytes(4))
    lobby = _pb(1, _pb(1, 3) + _pb(2, b"Watcher"))
    info += b"\x38\x03" + struct.pack("<I", len(lobby)) + lobby
    slots = (bytes([1, 100, 2, 0, 0, 0, 0x08, 1, 100]) + bytes([2, 100, 2, 0, 1, 1, 0x01, 1, 100])
             + bytes([0, 100, 0, 0, 0, 2, 0x20, 1, 100]))
    body = bytes([3]) + slots + struct.pack("<I", 1234) + bytes([3, 3])
    info += b"\x19" + struct.pack("<H", len(body)) + body + b"\x1a\1\0\0\0"
    block = bytes([1]) + struct.pack("<H", len(actions)) + actions
    turn = b"\x1f" + struct.pack("<HH", len(block) + 2, 250) + block
    chat = b"gg\0"
    chat_rec = b"\x20\x02" + struct.pack("<H", len(chat) + 5) + b"\x20" + struct.pack("<I", 0) + chat
    leave = b"\x17" + struct.pack("<IBII", 12, 2, 8, 0)
    return info + turn + extra_records + chat_rec + leave


def _replay(stream: bytes, version: int = 10200) -> bytes:
    packed = zlib.compress(stream)
    reforged = version >= 10000
    block = struct.pack("<III" if reforged else "<HHI", len(packed), 8192, 0) + packed
    header = w3g.MAGIC + struct.pack("<5I", 68, 68 + len(block), 1, len(stream), 1)
    header += struct.pack("<4sIHHII", b"PX3W", version, 7000, 0x8000, 60000, 0)
    assert len(header) == 68
    return header + block


ORDERS = (b"\x7a" + struct.pack("<II", 7, 7) + b"iesA" + b"403I"           # command card: buy item I304
          + b"\x10" + struct.pack("<HI", 0x40, 0x49333034) + b"\xff" * 8    # the order it leads to
          + b"\x12" + struct.pack("<HI", 0, 851971) + b"\xff" * 8 + struct.pack("<ffII", 100, 200, 9, 9)
          + b"\x16\x01" + struct.pack("<H", 1) + struct.pack("<II", 7, 7)
          + b"\x76\x2c" + struct.pack("<ff", 1.5, 2.5) + b"\x01")


@pytest.mark.parametrize("version", [10200, 26])
def test_reads_game_info_orders_chat_and_leaves(version):
    rp = w3g.parse(_replay(_stream(ORDERS), version), {852685: "valiantcharge"})
    assert rp.header["build"] == 7000 and rp.header["multiplayer"] and rp.header["blocks_read"] == 1
    assert rp.game["map"] == "Maps/Test.w3x" and rp.game["creator"] == "Host" and rp.game["map_size"] == [64, 96]
    assert rp.players == {1: "Host", 2: "Guest", 3: "Watcher"} and rp.game["random_seed"] == 1234
    assert [(s["player_id"], s["team"], s["race"]) for s in rp.slots] == [(1, 0, "undead"), (2, 1, "human")]
    assert [a["action"] for a in rp.actions] == ["command", "order", "order_target", "select", "mouse"]
    command, order, smart = rp.actions[:3]
    assert command["id"] == "Asei" and command["then"] == {"id": "I304"} and command["unit"] == 7
    assert order["id"] == "I304" and order["time_ms"] == 250 and order["player_id"] == 1
    assert smart["order"] == "smart" and smart["target"] == {"x": 100.0, "y": 200.0, "unit": 9}
    assert rp.actions[4]["x"] == 1.5 and rp.actions[4]["button"] == 1
    assert rp.chat == [{"time_ms": 250, "player_id": 2, "to": "all", "text": "gg"}]
    assert rp.leaves == [{"time_ms": 250, "player_id": 2, "reason": 12, "result": "lost"}]
    assert rp.end["reason"] == "end of data" and rp.unknown == {}


def test_an_unknown_action_cuts_only_that_block():
    rp = w3g.parse(_replay(_stream(ORDERS[:17] + b"\xee\x01\x02" + ORDERS[17:])))
    assert rp.unknown == {"0xee": 1} and [a["action"] for a in rp.actions] == ["command"]
    assert rp.chat and rp.leaves and rp.end["reason"] == "end of data"


def test_an_unknown_record_ends_the_stream_where_it_is():
    rp = w3g.parse(_replay(_stream(ORDERS, extra_records=b"\x99\0\0")))
    assert rp.end["reason"] == "unknown record 0x99" and len(rp.actions) == 5 and rp.chat == []


def test_rejects_what_is_not_a_replay():
    with pytest.raises(FormatError, match="not a Warcraft III replay"):
        w3g.parse(bytes(4096))   # TempReplay.w3g while its game runs


def _local_replays():
    root = config.documents()
    found = [*root.glob("BattleNet/*/Replays/*.w3g"), *root.glob("Logs/*.w3g")] if root.is_dir() else []
    return [p for p in found if p.stat().st_size and p.read_bytes()[:28] == w3g.MAGIC]


@pytest.mark.skipif(not _local_replays(), reason="no local replays")
def test_local_replays_parse_to_the_end():
    for path in _local_replays():
        rp = w3g.parse(path.read_bytes())
        assert rp.end["reason"] in ("end of data", "padding"), (path.name, rp.end)
        assert rp.unknown == {}, (path.name, rp.unknown)
        assert rp.players and rp.slots and rp.actions
        assert abs(rp.end["time_ms"] - rp.header["length_ms"]) < 5000, path.name


def test_replay_read_tool_filters_and_bounds(tmp_path):
    import json

    from wc3mcp.errors import ToolError
    from wc3mcp.ops.replay import replay_read

    path = tmp_path / "game.w3g"
    path.write_bytes(_replay(_stream(ORDERS)))
    out = replay_read(str(path))
    json.dumps(out, allow_nan=False)
    assert [a["action"] for a in out["actions"]] == ["command", "order", "order_target"] and out["total"] == 3
    assert out["actions"][0]["time"] == "0:00.2" and out["parsed"]["reached_end"]
    host = out["players"][0]
    assert host["name"] == "Host" and host["host"] and host["race"] == "undead" and host["action_counts"]["mouse"] == 1
    assert out["players"][2]["slot"] is None and out["chat"][0]["text"] == "gg" and out["leaves"][0]["result"] == "lost"
    one = replay_read(str(path), player="guest", kinds=["mouse"])
    assert one["total"] == 0 and one["chat"][0]["player"] == 2
    assert replay_read(str(path), kinds=["mouse", "select"], limit=1, offset=1)["actions"][0]["action"] == "mouse"
    for bad in ({"player": "nobody"}, {"kinds": ["dance"]}):
        with pytest.raises(ToolError):
            replay_read(str(path), **bad)
    (tmp_path / "TempReplay.w3g").write_bytes(bytes(100))
    with pytest.raises(ToolError, match="no w3g header"):
        replay_read(str(tmp_path / "TempReplay.w3g"))
