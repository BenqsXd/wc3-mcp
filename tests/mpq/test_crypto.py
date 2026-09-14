import struct

from wc3mcp.mpq.crypto import (HASH_A, HASH_B, HASH_KEY, M, decrypt, detect_sector_key, encrypt,
                               file_key, hash_string)


def test_known_table_keys():
    assert hash_string("(hash table)", HASH_KEY) == 0xC3AF3770
    assert hash_string("(block table)", HASH_KEY) == 0xEC83B3A3


def test_hash_ignores_case_and_slash_style():
    assert hash_string("war3map.J", HASH_A) == hash_string("WAR3MAP.j", HASH_A)
    assert hash_string("a/b.txt", HASH_B) == hash_string("A\\B.TXT", HASH_B)


def test_encrypt_decrypt_roundtrip_keeps_tail_bytes():
    data = bytes(range(256)) * 3 + b"xyz"
    enc = encrypt(data, 0x12345678)
    assert enc != data and enc[-3:] == b"xyz"
    assert decrypt(enc, 0x12345678) == data


def test_file_key_uses_basename_and_fix_key():
    plain = file_key("dir\\war3map.j", 100, 50, fix_key=False)
    assert plain == hash_string("war3map.j", HASH_KEY)
    assert file_key("war3map.j", 100, 50, fix_key=True) == ((plain + 100) ^ 50) & M


def test_detect_sector_key_recovers_file_key():
    key = file_key("war3mapImported\\x.blp", 0x1234, 10000, fix_key=True)
    table = struct.pack("<4I", 16, 900, 1800, 2400)  # 3 sectors: first offset = (3 + 1) * 4
    enc = encrypt(table, (key - 1) & M)
    assert detect_sector_key(enc, 4096, 16) == key
