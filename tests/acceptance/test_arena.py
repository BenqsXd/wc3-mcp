"""Phase 6 acceptance, tool level: the hero-arena project builds through the MCP tools, validates and reopens with
everything in place."""
import pytest

from arena import ICON, MODEL, VARIANTS, build, tool
from corpus import HAVE_INSTALL

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    return build(tmp_path_factory.mktemp("arena"))


@pytest.mark.parametrize("variant", VARIANTS)
def test_maps_reopen_with_everything_in_place(project, variant):
    built = project["maps"][variant]
    p = str(built["path"])
    tool("map_open", path=p)
    try:
        assert tool("info_get", path=p)["script_language"] == ("lua" if variant == "lua" else "jass")
        for kind, id_ in (("unit", built["hero"]), ("ability", built["ability"]), ("item", built["item"])):
            assert id_ in [o["id"] for o in tool("objdata_list", path=p, kind=kind, custom_only=True)["objects"]]
        assert [r["name"] for r in tool("elements_list", path=p, kind="region")["items"]] == ["Arena"]
        hero, = tool("placed_list", path=p, kind="unit", type_id=built["hero"])["items"]
        assert (hero["owner"], hero["x"], hero["y"], hero["script_name"]) == (0, 0.0, 0.0, built["champion"])
        imports = {i["path"].replace("/", "\\") for i in tool("imports_edit", path=p)["imports"]}
        assert {ICON, MODEL, "war3mapImported\\HeroArena.ai"} <= imports
        triggers = {t["name"]: t["type"] for t in tool("triggers_tree", path=p)["triggers"]}
        assert triggers["Arena Report"] == ("gui" if variant == "gui" else "text")
        assert "Start AI HeroArena" in triggers
        assert tool("map_validate", path=p)["errors"] == []
        assert tool("script_validate", path=p)["ok"]
    finally:
        tool("map_close", path=p, discard=True)


def test_campaign_holds_two_maps(project):
    c = str(project["campaign"])
    tool("map_open", path=c)
    try:
        campaign = tool("campaign_get", path=c)
        assert [b["map"] for b in campaign["buttons"]] == ["HeroArenaGUI.w3x", "HeroArenaJASS.w3x"]
        assert sorted(m["name"] for m in campaign["maps"]) == ["HeroArenaGUI.w3x", "HeroArenaJASS.w3x"]
    finally:
        tool("map_close", path=c, discard=True)
