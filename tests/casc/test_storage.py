import hashlib

import pytest

from corpus import INSTALL, needs_install
from wc3mcp.casc.storage import open_storage

pytestmark = needs_install


@pytest.fixture(scope="module")
def storage():
    return open_storage(INSTALL)


def test_reads_match_root_content_keys(storage):
    for path in ("War3.w3mod:Scripts/common.j", "war3.w3mod:units\\unitdata.slk",
                 "War3.w3mod:_Locales/enUS.w3mod:UI/TriggerStrings.txt"):
        data = storage.read(path)
        assert data and hashlib.md5(data).hexdigest() == storage.root_info[storage.norm(path)][1]


def test_list_glob_and_missing(storage):
    assert storage.list("*/common.j")
    assert storage.read("no/such/file") is None


def test_resolve_applies_locale_and_balance_layers(storage):
    assert storage.resolve("Units/UnitData.slk") == "War3.w3mod:Units/UnitData.slk"
    assert (storage.resolve("Units/UnitData.slk", balance="Custom_V1")
            == "War3.w3mod:_Balance/Custom_V1.w3mod:Units/UnitData.slk")
    assert (storage.resolve("Units/HumanUnitStrings.txt", locale="enUS")
            == "War3.w3mod:_Locales/enUS.w3mod:Units/HumanUnitStrings.txt")


def test_build_name(storage):
    assert storage.build_name.split(".")[0].isdigit()
