import os
import struct
import zlib

import pytest

from corpus import ladder_maps
from wc3mcp.mpq.reader import HASH_EMPTY, Archive, MpqError
from wc3mcp.mpq.writer import SPECIAL, capture_unnamed, write_archive


def test_roundtrip_edge_sizes():
    files = {"war3map.j": b"function main takes nothing returns nothing\nendfunction\n" * 200,
             "empty.txt": b"", "exact.bin": bytes(range(256)) * 16, "over.bin": b"\x01" * 4097,
             "war3mapImported\\noise.bin": os.urandom(10_000)}
    arc = Archive(write_archive(files))
    assert (arc.offset, arc.format_version, arc.sector_size) == (0, 0, 4096)
    for name, data in files.items():
        assert arc.read(name) == data
    assert sorted(arc.listfile_names()) == sorted(files)


def test_flags_and_attributes_match_editor_saves():
    data = b"hello" * 1000
    arc = Archive(write_archive({"a.txt": data}))
    assert arc.blocks[arc.find("a.txt").block].flags == 0x80000200
    for name in SPECIAL:
        assert arc.blocks[arc.find(name).block].flags == 0x80030200
    attrs = arc.read("(attributes)")
    crcs = struct.unpack_from(f"<{len(arc.blocks)}I", attrs, 8)
    assert struct.unpack_from("<2I", attrs) == (100, 1) and len(attrs) == 8 + 4 * len(arc.blocks)
    assert crcs[arc.find("a.txt").block] == zlib.crc32(data)
    assert crcs[arc.find("(listfile)").block] == zlib.crc32(arc.read("(listfile)"))
    assert crcs[arc.find("(attributes)").block] == 0


@pytest.mark.parametrize("count", [1, 30, 31, 100])
def test_hash_table_is_power_of_two_and_large_enough(count):
    arc = Archive(write_archive({f"f{i}.txt": b"x" for i in range(count)}))
    size = len(arc.hashes)
    assert size & (size - 1) == 0 and size >= count + 2


def test_prefix_is_kept():
    prefix = b"HM3W" + bytes(508)
    data = write_archive({"a": b"1"}, prefix=prefix)
    assert data[:512] == prefix and Archive(data).offset == 512 and Archive(data).read("a") == b"1"


def test_encrypt_names_and_no_listfile():
    arc = Archive(write_archive({"secret.txt": b"s" * 5000}, encrypt_names=frozenset({"secret.txt"}),
                                listfile=False))
    assert arc.read("secret.txt") == b"s" * 5000
    assert arc.find("(listfile)") is None
    assert arc.blocks[arc.find("secret.txt").block].flags == 0x80030200


def test_unnamed_entries_survive_repacking():
    files = {f"known{i}.txt": f"k{i}".encode() * 2000 for i in range(4)}
    hidden = {"hidden\\plain.txt": b"plain" * 900, "hidden\\secret.txt": b"secret" * 900}
    src = Archive(write_archive(files | hidden, encrypt_names=frozenset({"hidden\\secret.txt"}), listfile=False))
    unnamed = src.unnamed_entries(list(files) + ["(attributes)"])
    assert len(unnamed) == 2
    out = Archive(write_archive(
        {"new\\big.bin": os.urandom(50_000)},
        preserved=tuple(capture_unnamed(src, e) for e in unnamed),
        hash_size=len(src.hashes),
        reserved_slots=frozenset(e.index for e in src.hashes if e.block != HASH_EMPTY),
        sector_size=src.sector_size))
    for name, data in hidden.items():
        assert out.read(name) == data


def test_rejects_overfull_fixed_table():
    with pytest.raises(MpqError):
        write_archive({f"f{i}": b"x" for i in range(10)}, hash_size=8)


MAPS = ladder_maps()


@pytest.mark.skipif(not MAPS, reason="no ladder maps in Documents")
@pytest.mark.parametrize("path", MAPS[:25], ids=lambda p: p.name)  # ponytail: 25 keeps the suite fast; reader test covers all
def test_ladder_maps_repack_losslessly(path):
    src = Archive.open(path)
    files = {n: src.read(n) for n in src.list() if n not in SPECIAL}
    out = Archive(write_archive(files, prefix=src.prefix, sector_size=src.sector_size))
    assert {n: out.read(n) for n in files} == files
