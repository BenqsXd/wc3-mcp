"""BLTE containers (Blizzard's chunked, optionally compressed file encoding)."""
import struct
import zlib


class EncryptedChunk(Exception):
    pass


def lz4_block(src: bytes, dst: bytearray | None = None) -> bytearray:
    """Decode one raw LZ4 block (no frame header)."""
    dst = bytearray() if dst is None else dst
    i, n = 0, len(src)
    while i < n:
        tok = src[i]
        i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        dst += src[i:i + lit]
        i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        ml = tok & 15
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(dst) - off
        if off >= ml:
            dst += dst[start:start + ml]
        else:  # overlapping copy
            for k in range(ml):
                dst.append(dst[start + k])
    return dst


def blte_decode(data: bytes, stats: dict | None = None) -> bytes:
    if data[:4] != b"BLTE":
        raise ValueError("not BLTE")
    header_size = int.from_bytes(data[4:8], "big")
    if header_size == 0:  # single chunk, no frame table
        return _chunk(memoryview(data)[8:], stats)
    if data[8] != 0x0F:
        raise ValueError(f"bad BLTE flags {data[8]:#x}")
    count = int.from_bytes(data[9:12], "big")
    out, pos = [], header_size
    for k in range(count):
        encoded_size, _decoded_size = struct.unpack_from(">II", data, 12 + 24 * k)  # followed by a 16-byte MD5
        out.append(_chunk(memoryview(data)[pos:pos + encoded_size], stats))
        pos += encoded_size
    return b"".join(out)


def _chunk(mv: memoryview, stats: dict | None) -> bytes:
    mode = chr(mv[0])
    if stats is not None:
        stats[mode] = stats.get(mode, 0) + 1
    body = mv[1:]
    if mode == "N":
        return bytes(body)
    if mode == "Z":
        return zlib.decompress(body)
    if mode == "F":
        return blte_decode(bytes(body), stats)
    if mode == "4":
        # wowdev.wiki/BLTE: u8 version, u64be decoded size, u8 block shift, then u32be-sized LZ4 blocks.
        # ponytail: no local '4' chunk seen in 3.0.0.24268; covered only by the lz4_block unit test.
        decoded_size = int.from_bytes(body[1:9], "big")
        p, dst = 10, bytearray()
        while len(dst) < decoded_size and p < len(body):
            n = int.from_bytes(body[p:p + 4], "big")
            p += 4
            lz4_block(bytes(body[p:p + n]), dst)
            p += n
        return bytes(dst)
    if mode == "E":
        raise EncryptedChunk("encrypted BLTE chunk")
    raise ValueError(f"unknown BLTE mode {mode!r}")
