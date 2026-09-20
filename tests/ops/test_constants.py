"""Gameplay constants (war3mapMisc.txt) over the game's own Units/MiscGame.txt and Units/MiscData.txt."""
import pytest

from corpus import HAVE_INSTALL, _storage
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.constants import MAP_FILE, _parse, constants_edit, constants_get
from wc3mcp.ops.newmap import new_map

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)


@pytest.fixture
def project(tmp_path, catalog):
    return new_map(str(tmp_path / "C.w3x"), catalog, width=32, height=32, players=2)


def test_comments_and_blank_lines_are_not_constants():
    text = "[Misc]\n\n// the angle in degrees structures face\nBuildingAngle=270\nBoneDecayTime=88 // seconds\n"
    assert _parse(text) == {"BuildingAngle": "270", "BoneDecayTime": "88"}


def test_the_game_defines_the_hero_constants_and_the_map_defines_none(project, catalog):
    doc = constants_get(project, catalog)
    found = {row["key"]: row for row in doc["constants"]}
    assert found["MaxHeroLevel"]["value"] == "10" and found["MaxHeroLevel"]["source"] == "Units/MiscGame.txt"
    assert found["HeroAbilityLevelSkip"]["value"] == "2" and not found["HeroAbilityLevelSkip"]["modified"]
    assert found["BuildingAngle"]["source"] == "Units/MiscData.txt"   # the second file counts too
    assert doc["has_file"] is False and doc["count"] > 150
    assert constants_get(project, catalog, modified_only=True)["constants"] == []


def test_setting_the_level_cap_writes_the_map_file_and_resetting_removes_it(project, catalog):
    result = constants_edit(project, catalog, {"MaxHeroLevel": 25, "MaxUnitLevel": 25, "HeroAbilityLevelSkip": 1})
    assert result["changed"] and result["count"] == 3
    text = project.read(MAP_FILE).decode("utf-8")
    assert text.startswith("[Misc]\n") and "MaxHeroLevel=25\n" in text and "MaxUnitLevel=25\n" in text
    row = constants_get(project, catalog, ["MaxHeroLevel"])["constants"][0]
    assert row["value"] == "25" and row["modified"] and row["default"] == "10"
    assert [r["key"] for r in constants_get(project, catalog, modified_only=True)["constants"]] == [
        "HeroAbilityLevelSkip", "MaxHeroLevel", "MaxUnitLevel"]
    assert constants_edit(project, catalog, {"MaxHeroLevel": 25})["changed"] is False   # the same value again
    assert constants_edit(project, catalog, reset=["MaxHeroLevel", "MaxUnitLevel", "HeroAbilityLevelSkip"])["changed"]
    assert MAP_FILE.lower() not in {f["name"].lower() for f in project.list_files()}
    assert constants_get(project, catalog, modified_only=True)["constants"] == []


def test_a_misspelt_or_unusable_value_is_refused(project, catalog):
    with pytest.raises(ToolError) as e:
        constants_edit(project, catalog, {"MaxHerosLevel": 25})
    assert e.value.code == "unknown_constant" and "constants_get" in e.value.hint
    with pytest.raises(ToolError) as e:
        constants_edit(project, catalog, {"MaxHeroLevel": "twenty-five"})
    assert e.value.code == "bad_value" and "read as 0" in e.value.message
    with pytest.raises(ToolError) as e:
        constants_get(project, catalog, ["NoSuchConstant"])
    assert e.value.code == "unknown_constant"
    with pytest.raises(ToolError) as e:
        constants_edit(project, catalog)
    assert e.value.code == "bad_value"


def test_a_file_written_by_hand_keeps_its_keys_and_unknown_ones_are_flagged(project, catalog):
    project.write(MAP_FILE, b"[Misc]\nMaxHeroLevel=25\nNeedHeroXPFormulaA=1\nTotallyMadeUp=3\n")
    rows = {r["key"]: r for r in constants_get(project, catalog, modified_only=True)["constants"]}
    assert rows["NeedHeroXPFormulaA"]["value"] == "1" and rows["TotallyMadeUp"].get("unknown") is True
    constants_edit(project, catalog, {"MaxUnitLevel": 25})
    text = project.read(MAP_FILE).decode("utf-8")
    assert "TotallyMadeUp=3" in text and "MaxUnitLevel=25" in text   # nothing of the map's own is lost


def test_map_validate_flags_a_constant_the_game_does_not_know(project, catalog):
    from wc3mcp.ops.validate import validate

    project.write(MAP_FILE, b"[Misc]\nMaxHeroLevel=25\nHeroAbilitySkipLevel=1\n")
    files = {f["name"]: project.read(f["name"]) for f in project.list_files()}
    report = validate(files, catalog)
    flagged = [w for w in report["warnings"] if w["check"] == "constant"]
    assert len(flagged) == 1 and "HeroAbilitySkipLevel" in flagged[0]["message"]
