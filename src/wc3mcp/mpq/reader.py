"""Tolerant read-only MPQ access (protected Warcraft III maps included)."""
from __future__ import annotations  # Archive.list() would shadow builtin list in later annotations

import bz2
import struct
import zlib
from dataclasses import dataclass

from .crypto import HASH_A, HASH_B, HASH_KEY, HASH_OFFSET, M, decrypt, file_key, hash_string
from .names import recover_names

F_IMPLODE = 0x00000100
F_COMPRESS = 0x00000200
F_ENCRYPTED = 0x00010000
F_FIX_KEY = 0x00020000
F_SINGLE_UNIT = 0x01000000
F_SECTOR_CRC = 0x04000000
F_EXISTS = 0x80000000
HASH_EMPTY, HASH_DELETED = 0xFFFFFFFF, 0xFFFFFFFE
MAX_FILE_SIZE = 512 * 1024 * 1024


class MpqError(Exception):
    pass


@dataclass(frozen=True)
class HashEntry:
    index: int
    name_a: int
    name_b: int
    locale: int
    platform: int
    block: int


@dataclass(frozen=True)
class Block:
    pos: int
    csize: int
    fsize: int
    flags: int


class Archive:
    def __init__(self, data: bytes, path: str | None = None):
        self.data, self.path, self.problems = data, path, []
        self.offset = self._find_header()
        (_, self.archive_size, self.format_version, shift, hash_pos, block_pos, hash_n,
         block_n) = struct.unpack_from("<IIHHIIII", data, self.offset + 4)
        self.sector_size = 512 << (shift & 0x1F)
        self.hashes = [HashEntry(i, a, b, c & 0xFFFF, c >> 16, blk)
                       for i, (a, b, c, blk) in enumerate(self._table(hash_pos, hash_n, "(hash table)"))]
        self.blocks = [Block(*e) for e in self._table(block_pos, block_n, "(block table)")]

    @classmethod
    def open(cls, path) -> "Archive":
        with open(path, "rb") as f:
            return cls(f.read(), str(path))

    @property
    def prefix(self) -> bytes:
        """Bytes before the MPQ header (e.g. a 512-byte HM3W map header)."""
        return self.data[:self.offset]

    def _find_header(self) -> int:
        d = self.data
        for off in range(0, len(d) - 31, 0x200):
            magic = d[off:off + 4]
            if magic == b"MPQ\x1b":  # user-data header points at the real one
                real = off + struct.unpack_from("<I", d, off + 8)[0]
                if d[real:real + 4] == b"MPQ\x1a":
                    return real
            if magic == b"MPQ\x1a":
                return off
        raise MpqError("no MPQ header found")

    def _table(self, pos: int, count: int, key_name: str) -> list[tuple[int, int, int, int]]:
        start = (self.offset + pos) & M
        n = max(0, min(count, (len(self.data) - start) // 16))
        if n < count:
            self.problems.append(f"{key_name}: {count} entries declared, {n} present")
        raw = decrypt(self.data[start:start + n * 16], hash_string(key_name, HASH_KEY))
        return [struct.unpack_from("<4I", raw, i * 16) for i in range(n)]

    def _live(self, e: HashEntry) -> bool:
        return e.block < len(self.blocks) and bool(self.blocks[e.block].flags & F_EXISTS)

    def find(self, name: str) -> HashEntry | None:
        n = len(self.hashes)
        if not n:
            return None
        a, b = hash_string(name, HASH_A), hash_string(name, HASH_B)
        if n & (n - 1) == 0:  # regular table: probe like the game does
            i = start = hash_string(name, HASH_OFFSET) & (n - 1)
            while self.hashes[i].block != HASH_EMPTY:
                e = self.hashes[i]
                if e.name_a == a and e.name_b == b and self._live(e):
                    return e
                i = (i + 1) & (n - 1)
                if i == start:
                    break
        # ponytail: full scan for tables broken by map protectors; O(n) per miss, map tables are small
        return next((e for e in self.hashes if e.name_a == a and e.name_b == b and self._live(e)), None)

    def read(self, name: str) -> bytes | None:
        e = self.find(name)
        if e is None:
            return None
        blk = self.blocks[e.block]
        key = file_key(name, blk.pos, blk.fsize, bool(blk.flags & F_FIX_KEY)) if blk.flags & F_ENCRYPTED else None
        return self.read_block(e.block, key)

    def read_block(self, index: int, key: int | None) -> bytes:
        blk = self.blocks[index]
        if blk.fsize > MAX_FILE_SIZE:
            raise MpqError(f"block {index}: size {blk.fsize} exceeds {MAX_FILE_SIZE}")
        if blk.fsize == 0:
            return b""
        if blk.flags & F_ENCRYPTED and key is None:
            raise MpqError(f"block {index}: encrypted and its key is unknown")
        start = (self.offset + blk.pos) & M
        compressed = bool(blk.flags & (F_COMPRESS | F_IMPLODE))
        if blk.flags & F_SINGLE_UNIT:
            raw = self.data[start:start + blk.csize]
            if key is not None:
                raw = decrypt(raw, key)
            if compressed and blk.csize < blk.fsize:
                raw = self._decompress(raw, blk.fsize, blk.flags)
            return bytes(raw[:blk.fsize])
        ss = self.sector_size
        n = (blk.fsize + ss - 1) // ss
        if compressed:
            tbl = self.data[start:start + (n + 1) * 4]
            if len(tbl) < (n + 1) * 4:
                raise MpqError(f"block {index}: sector table past end of file")
            if key is not None:
                tbl = decrypt(tbl, (key - 1) & M)
            offs = struct.unpack(f"<{n + 1}I", tbl)
        else:
            offs = [i * ss for i in range(n)] + [blk.fsize]
        out = []
        for i in range(n):
            expect = min(ss, blk.fsize - i * ss)
            lo, hi = offs[i], offs[i + 1]
            chunk = self.data[start + lo:start + hi] if hi >= lo else b""
            if key is not None:
                chunk = decrypt(chunk, (key + i) & M)
            if compressed and len(chunk) < expect:
                chunk = self._decompress(chunk, expect, blk.flags)
            if len(chunk) < expect:
                self.problems.append(f"block {index} sector {i}: short by {expect - len(chunk)} bytes, zero-filled")
            out.append(bytes(chunk[:expect]).ljust(expect, b"\0"))
        return b"".join(out)

    def _decompress(self, buf: bytes, expect: int, flags: int) -> bytes:
        if not buf:
            self.problems.append("zero-length compressed unit, zero-filled")
            return bytes(expect)
        if flags & F_IMPLODE and not flags & F_COMPRESS:
            raise MpqError("PKWARE implode compression is not supported")
        mask, data = buf[0], buf[1:]
        if mask & ~0x12:
            raise MpqError(f"unsupported compression mask {mask:#04x}")
        if mask & 0x10:
            data = bz2.BZ2Decompressor().decompress(data, max_length=expect)
        if mask & 0x02:
            data = zlib.decompressobj().decompress(data, expect)  # bounded: no decompression bombs
        return data

    def listfile_names(self) -> list[str]:
        raw = self.read("(listfile)") or b""
        return [n.strip() for n in raw.decode("utf-8", "replace").replace(";", "\n").splitlines() if n.strip()]

    def list(self) -> list[str]:
        return recover_names(self)

    def unnamed_entries(self, names) -> list[HashEntry]:
        named = {e.index for e in map(self.find, names) if e is not None}
        return [e for e in self.hashes if self._live(e) and e.index not in named]
