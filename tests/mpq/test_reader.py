import struct
import zlib

import pytest

from corpus import ladder_maps
from wc3mcp.mpq.reader import Archive, MpqError

MAPS = ladder_maps()


def test_rejects_data_without_header():
    with pytest.raises(MpqError):
        Archive(b"not an mpq" * 100)


@pytest.mark.skipif(not MAPS, reason="no ladder maps in Documents")
@pytest.mark.parametrize("path", MAPS, ids=lambda p: p.name)
def test_ladder_map_files_match_attribute_crcs(path):
    arc = Archive.open(path)
    attrs = arc.read("(attributes)")
    version, flags = struct.unpack_from("<2I", attrs)
    assert (version, flags & 1) == (100, 1)
    crcs = struct.unpack_from(f"<{len(arc.blocks)}I", attrs, 8)
    names = arc.list()
    assert "war3map.w3i" in names and not arc.unnamed_entries(names)
    for name in names:
        entry = arc.find(name)
        data = arc.read(name)
        assert len(data) == arc.blocks[entry.block].fsize
        if name != "(attributes)":
            assert zlib.crc32(data) == crcs[entry.block], name
