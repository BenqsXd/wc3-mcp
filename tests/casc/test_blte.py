import struct
import zlib

from wc3mcp.casc.blte import blte_decode, lz4_block


def frame(chunks: list[bytes]) -> bytes:
    table = b"".join(struct.pack(">II", len(c), 0) + bytes(16) for c in chunks)
    return (b"BLTE" + struct.pack(">I", 12 + 24 * len(chunks)) + b"\x0f" + len(chunks).to_bytes(3, "big")
            + table + b"".join(chunks))


def test_single_raw_chunk():
    assert blte_decode(b"BLTE\0\0\0\0Nhello") == b"hello"


def test_framed_raw_and_zlib_chunks():
    assert blte_decode(frame([b"Nabc", b"Z" + zlib.compress(b"def")])) == b"abcdef"


def test_lz4_block_with_overlapping_match():
    assert lz4_block(bytes([0x32]) + b"abc" + b"\x03\x00") == b"abcabcabc"
