import struct

from wc3mcp.mpq.names import recover_names
from wc3mcp.mpq.reader import Archive
from wc3mcp.mpq.writer import write_archive


def test_recovers_names_without_listfile():
    files = {
        "war3map.w3i": b"info",
        "_Locales\\deDE.w3mod\\war3map.wts": b"STRING 1",
        "war3map.j": b'call AddSpecialEffect("war3mapImported\\\\fx.mdx", 0, 0)\n',
        "war3mapImported\\fx.mdx": b"MDLX",
        "war3mapImported\\icon.blp": b"BLP1",
        "war3map.imp": struct.pack("<II", 1, 1) + b"\x0dicon.blp\x00",
        "unreferenced\\x.txt": b"lost",
    }
    arc = Archive(write_archive(files, listfile=False))
    names = set(recover_names(arc))
    assert set(files) - {"unreferenced\\x.txt"} <= names
    assert "unreferenced\\x.txt" not in names
    assert len(arc.unnamed_entries(names)) == 1
