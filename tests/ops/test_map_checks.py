import pytest

from corpus import HAVE_INSTALL, _storage, open_sample, sample_map_ids
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.validate import validate

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs game data from the install")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)


def map_files(arc) -> dict:
    return {n: arc.read(n) for n in arc.list()
            if ("\\" not in n and n.lower().startswith("war3map")) or n.lower().startswith("scripts\\")}


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_shipped_maps_have_no_errors(map_id, catalog):
    arc = open_sample(map_id)
    result = validate(map_files(arc), catalog, has_file=lambda name: arc.find(name) is not None)
    assert result["errors"] == []


def test_broken_references_are_errors(catalog):
    arc = open_sample(sample_map_ids()[0])
    files = map_files(arc)
    files.pop("war3map.j", None)
    files.pop("war3map.lua", None)
    result = validate(files, catalog, has_file=lambda name: False)
    assert any(e["check"] == "script_language" for e in result["errors"])
