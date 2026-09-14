"""Storm hashing and encryption used by MPQ archives."""
import struct

M = 0xFFFFFFFF
HASH_OFFSET, HASH_A, HASH_B, HASH_KEY = 0, 1, 2, 3


def _crypt_table() -> tuple[int, ...]:
    t = [0] * 0x500
    seed = 0x00100001
    for i in range(0x100):
        idx = i
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            hi = (seed & 0xFFFF) << 16
            seed = (seed * 125 + 3) % 0x2AAAAB
            t[idx] = hi | (seed & 0xFFFF)
            idx += 0x100
    return tuple(t)


CRYPT = _crypt_table()


def hash_string(name: str | bytes, htype: int) -> int:
    """Storm HashString: ASCII-uppercased, '/' treated as '\\'."""
    raw = name.encode("utf-8") if isinstance(name, str) else name
    s1, s2 = 0x7FED7FED, 0xEEEEEEEE
    for ch in raw.replace(b"/", b"\\").upper():
        s1 = CRYPT[(htype << 8) + ch] ^ ((s1 + s2) & M)
        s2 = (ch + s1 + s2 + (s2 << 5) + 3) & M
    return s1


def _next_key(key: int) -> int:
    return ((((~key) << 0x15) + 0x11111111) & M) | (key >> 0x0B)


def decrypt(data: bytes, key: int) -> bytes:
    n = len(data) // 4
    out, seed = [], 0xEEEEEEEE
    for w in struct.unpack_from(f"<{n}I", data):
        seed = (seed + CRYPT[0x400 + (key & 0xFF)]) & M
        c = w ^ ((key + seed) & M)
        out.append(c)
        key = _next_key(key)
        seed = (c + seed + (seed << 5) + 3) & M
    return struct.pack(f"<{n}I", *out) + bytes(data[n * 4:])


def encrypt(data: bytes, key: int) -> bytes:
    n = len(data) // 4
    out, seed = [], 0xEEEEEEEE
    for c in struct.unpack_from(f"<{n}I", data):
        seed = (seed + CRYPT[0x400 + (key & 0xFF)]) & M
        out.append(c ^ ((key + seed) & M))
        key = _next_key(key)
        seed = (c + seed + (seed << 5) + 3) & M
    return struct.pack(f"<{n}I", *out) + bytes(data[n * 4:])


def file_key(name: str, block_pos: int, fsize: int, fix_key: bool) -> int:
    key = hash_string(name.replace("/", "\\").rsplit("\\", 1)[-1], HASH_KEY)
    return ((key + block_pos) ^ fsize) & M if fix_key else key


def detect_sector_key(enc: bytes, sector_size: int, first_offset: int) -> int | None:
    """Recover the file key of an encrypted sector offset table whose first entry is known
    (StormLib DetectFileKeyBySectorSize). The table is encrypted with key - 1."""
    e0, e1 = struct.unpack_from("<2I", enc)
    k1k2 = ((e0 ^ first_offset) - 0xEEEEEEEE) & M
    for i in range(0x100):
        key = (k1k2 - CRYPT[0x400 + i]) & M
        seed = (0xEEEEEEEE + CRYPT[0x400 + (key & 0xFF)]) & M
        if e0 ^ ((key + seed) & M) != first_offset:
            continue
        nkey = _next_key(key)
        seed = (first_offset + seed + (seed << 5) + 3) & M
        seed = (seed + CRYPT[0x400 + (nkey & 0xFF)]) & M
        if e1 ^ ((nkey + seed) & M) <= first_offset + sector_size:
            return (key + 1) & M
    return None
