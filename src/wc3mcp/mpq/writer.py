"""Write MPQ archives the way the World Editor saves maps: v0 header at the start, zlib sectors,
encrypted (listfile)/(attributes), CRC32 attributes table."""
import struct
import zlib
from dataclasses import dataclass

from .crypto import HASH_A, HASH_B, HASH_KEY, HASH_OFFSET, M, decrypt, detect_sector_key, encrypt, file_key, hash_string
from .reader import (F_COMPRESS, F_ENCRYPTED, F_EXISTS, F_FIX_KEY, F_SECTOR_CRC, F_SINGLE_UNIT, HASH_DELETED,
                     HASH_EMPTY, Archive, HashEntry, MpqError)

SPECIAL = ("(listfile)", "(attributes)")
_EMPTY_SLOT = struct.pack("<IIHHI", M, M, 0xFFFF, 0xFFFF, HASH_EMPTY)
_DELETED_SLOT = struct.pack("<IIHHI", M, M, 0xFFFF, 0xFFFF, HASH_DELETED)


@dataclass(frozen=True)
class RawEntry:
    """A file whose name is unknown, carried over from a source archive without decoding."""
    hash_index: int
    name_a: int
    name_b: int
    locale: int
    platform: int
    data: bytes       # stored bytes exactly as in the source
    fsize: int
    flags: int
    src_pos: int
    key: int | None   # file key at src_pos when encrypted and recoverable


def capture_unnamed(archive: Archive, entry: HashEntry) -> RawEntry:
    blk = archive.blocks[entry.block]
    start = (archive.offset + blk.pos) & M
    key = None
    if blk.flags & F_ENCRYPTED and blk.flags & F_COMPRESS and not blk.flags & F_SINGLE_UNIT and blk.fsize:
        n = (blk.fsize + archive.sector_size - 1) // archive.sector_size
        first = (n + 1 + (1 if blk.flags & F_SECTOR_CRC else 0)) * 4
        key = detect_sector_key(archive.data[start:start + 8], archive.sector_size, first)
    return RawEntry(entry.index, entry.name_a, entry.name_b, entry.locale, entry.platform,
                    archive.data[start:start + blk.csize], blk.fsize, blk.flags, blk.pos, key)


def _relocate(e: RawEntry, new_pos: int, sector_size: int) -> bytes:
    """Stored bytes of `e` valid at `new_pos` (FIX_KEY encryption depends on the block position)."""
    if not (e.flags & F_ENCRYPTED and e.flags & F_FIX_KEY) or e.fsize == 0 or new_pos == e.src_pos:
        return e.data
    if e.key is None or e.flags & (F_SINGLE_UNIT | F_SECTOR_CRC) or not e.flags & F_COMPRESS:
        raise MpqError(f"cannot move encrypted unnamed file in hash slot {e.hash_index}: key not recoverable")
    new_key = ((((e.key ^ e.fsize) - e.src_pos) + new_pos) & M) ^ e.fsize
    n = (e.fsize + sector_size - 1) // sector_size
    table = struct.unpack(f"<{n + 1}I", decrypt(e.data[:(n + 1) * 4], (e.key - 1) & M))
    out = bytearray(e.data)
    out[:(n + 1) * 4] = encrypt(struct.pack(f"<{n + 1}I", *table), (new_key - 1) & M)
    for i in range(n):
        lo, hi = table[i], table[i + 1]
        if not lo <= hi <= len(e.data):
            raise MpqError(f"unnamed file in hash slot {e.hash_index}: bad sector table")
        out[lo:hi] = encrypt(decrypt(e.data[lo:hi], (e.key + i) & M), (new_key + i) & M)
    return bytes(out)


def _store(data: bytes, pos: int, sector_size: int, key_name: str | None) -> tuple[bytes, int]:
    if not data:
        return b"", F_EXISTS
    n = (len(data) + sector_size - 1) // sector_size
    sectors = []
    for i in range(n):
        raw = data[i * sector_size:(i + 1) * sector_size]
        z = zlib.compress(raw, 9)
        sectors.append(b"\x02" + z if len(z) + 1 < len(raw) else raw)
    offsets = [(n + 1) * 4]
    for s in sectors:
        offsets.append(offsets[-1] + len(s))
    table = struct.pack(f"<{n + 1}I", *offsets)
    flags = F_EXISTS | F_COMPRESS
    if key_name is not None:
        key = file_key(key_name, pos, len(data), fix_key=True)
        table = encrypt(table, (key - 1) & M)
        sectors = [encrypt(s, (key + i) & M) for i, s in enumerate(sectors)]
        flags |= F_ENCRYPTED | F_FIX_KEY
    return table + b"".join(sectors), flags


def write_archive(files: dict[str, bytes], *, preserved: tuple[RawEntry, ...] = (), prefix: bytes = b"",
                  hash_size: int | None = None, reserved_slots: frozenset[int] = frozenset(),
                  sector_size: int = 4096, encrypt_names: frozenset[str] = frozenset(),
                  listfile: bool = True) -> bytes:
    if len(prefix) % 0x200:
        raise MpqError("prefix length must be a multiple of 512")
    if sector_size < 512 or sector_size & (sector_size - 1):
        raise MpqError("sector size must be a power of two >= 512")
    names = [n for n in files if n not in SPECIAL]
    count = len(names) + len(preserved) + (2 if listfile else 1)
    if hash_size is None:
        hash_size = max(4, 1 << (count - 1).bit_length())
    if hash_size & (hash_size - 1) or hash_size < count:
        raise MpqError(f"hash table of {hash_size} slots cannot hold {count} files")

    body = bytearray(32)  # header written last
    blocks: list[tuple[int, int, int, int]] = []
    crcs: list[int] = []
    slots: list[bytes | None] = [None] * hash_size

    for e in preserved:  # original slots first so their probe chains stay valid
        if e.hash_index >= hash_size or slots[e.hash_index] is not None:
            raise MpqError(f"hash slot {e.hash_index} unusable for a preserved file")
        pos = len(body)
        body.extend(_relocate(e, pos, sector_size))
        slots[e.hash_index] = struct.pack("<IIHHI", e.name_a, e.name_b, e.locale, e.platform, len(blocks))
        blocks.append((pos, len(body) - pos, e.fsize, e.flags))
        crcs.append(0)

    def add(name: str, data: bytes, encrypted: bool) -> None:
        pos = len(body)
        stored, flags = _store(data, pos, sector_size, name if encrypted else None)
        body.extend(stored)
        i = hash_string(name, HASH_OFFSET) & (hash_size - 1)
        while slots[i] is not None:
            i = (i + 1) & (hash_size - 1)
        slots[i] = struct.pack("<IIHHI", hash_string(name, HASH_A), hash_string(name, HASH_B), 0, 0, len(blocks))
        blocks.append((pos, len(stored), len(data), flags))
        crcs.append(zlib.crc32(data))

    for name in names:
        add(name, files[name], name in encrypt_names)
    if listfile:
        add("(listfile)", "".join(n + "\r\n" for n in names).encode("utf-8"), True)
    attributes = struct.pack(f"<II{len(crcs) + 1}I", 100, 1, *crcs, 0)  # the attributes entry itself stores 0
    add("(attributes)", attributes, True)

    hash_pos = len(body)
    table = b"".join(s if s is not None else (_DELETED_SLOT if i in reserved_slots else _EMPTY_SLOT)
                     for i, s in enumerate(slots))
    body.extend(encrypt(table, hash_string("(hash table)", HASH_KEY)))
    block_pos = len(body)
    body.extend(encrypt(b"".join(struct.pack("<4I", *b) for b in blocks), hash_string("(block table)", HASH_KEY)))
    shift = sector_size.bit_length() - 10  # sector size = 512 << shift
    struct.pack_into("<4sIIHHIIII", body, 0, b"MPQ\x1a", 32, len(body), 0, shift, hash_pos, block_pos,
                     hash_size, len(blocks))
    return prefix + bytes(body)
