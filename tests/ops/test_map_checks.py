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


def test_placed_objects_without_models_and_moved_starts_are_warnings(catalog):
    from wc3mcp.formats import doo, unitsdoo, w3i

    arc = open_sample(sample_map_ids()[0])
    files = map_files(arc)
    units = unitsdoo.parse(files["war3mapUnits.doo"])
    start = next(u for u in units.units if u.id == b"sloc")
    start.x += 512
    files["war3mapUnits.doo"] = unitsdoo.serialize(units)
    doodads = doo.parse(files["war3map.doo"]) if "war3map.doo" in files else doo.DoodadFile(8, 11)
    grass = doo.Doodad(b"LPgp", 0, 0.0, 0.0, 0.0, 0.0, [1.0, 1.0, 1.0], b"LPgp", 2, 255)
    doodads.doodads += [grass, grass]
    files["war3map.doo"] = doo.serialize(doodads)
    result = validate(files, catalog, has_file=lambda name: arc.find(name) is not None)
    models = [w["message"] for w in result["warnings"] if w["check"] == "model"]
    assert any(m.startswith("2 placed doodad(s) LPgp: ") and "GrassPatch.mdl" in m for m in models)
    starts = [w["message"] for w in result["warnings"] if w["check"] == "start_location"]
    player = next(p for p in w3i.parse(files["war3map.w3i"]).players if p.id == start.owner)
    assert starts == [f"player {start.owner}: the start location marker is at ({start.x:g}, {start.y:g}) but "
                      f"war3map.w3i starts the player at ({player.start_x:g}, {player.start_y:g}); move it with "
                      "placed_edit, which updates both"]
    imported = validate(files, catalog, has_file=lambda name: "grasspatch" in name.lower())
    assert not any("LPgp" in w["message"] for w in imported["warnings"] if w["check"] == "model")


def test_placed_variations_without_a_classic_model_are_warnings(catalog):
    from wc3mcp.formats import doo

    arc = open_sample(sample_map_ids()[0])
    files = map_files(arc)
    doodads = doo.parse(files["war3map.doo"]) if "war3map.doo" in files else doo.DoodadFile(8, 11)
    shrub = [doo.Doodad(b"ZPsh", v, 0.0, 0.0, 0.0, 0.0, [1.0, 1.0, 1.0], b"ZPsh", 2, 255) for v in (0, 3)]
    doodads.doodads += shrub
    files["war3map.doo"] = doo.serialize(doodads)
    models = [w["message"] for w in validate(files, catalog, has_file=lambda name: arc.find(name) is not None)["warnings"]
              if w["check"] == "model" and "ZPsh" in w["message"]]
    assert len(models) == 1 and models[0].startswith("1 placed doodad(s) ZPsh: ") and "Ruins_Shrub3.mdl" in models[0]


def test_command_card_pitfalls_are_warnings(catalog):
    from wc3mcp.formats import objmods

    def entry(base, new, **values):
        mods = [objmods.Mod(k.encode(), objmods.INT if isinstance(v, int) else objmods.STRING, v)
                for k, v in values.items()]
        return objmods.ObjectEntry(base.encode(), new.encode(), mods)

    units = objmods.ObjectMods(3, False)
    units.custom = [entry("htow", "h001", utra="h002"), entry("hfoo", "h002", ubpx=3, ubpy=1),
                    entry("ewsp", "e000", uabi="Awha"), entry("otau", "o000", uhpm=900),
                    entry("ewsp", "e001", uabi="Awha", ubui="")]
    result = validate({"war3map.w3u": objmods.serialize(units)}, catalog)
    found = {(w["check"], w["message"].split(":")[0]) for w in result["warnings"]}
    assert ("command_card", "unit h001") in found and ("inherited_builds", "unit e000") in found
    assert ("inherited_builds", "unit e001") not in found
    locked = [w["message"] for w in result["warnings"] if w["check"] == "locked_ability"]
    research = next(m.split()[1] for m in locked if "o000 (" in m)   # a Tauren ability's research (data-set dependent)
    clash = next(w["message"] for w in result["warnings"] if w["check"] == "command_card")
    assert clash.startswith("unit h001: h002, Rally share button position (3, 1)")
    assert not [w for w in result["warnings"] if w["check"] == "command_card" and "unit h00" not in w["message"]]
    scripted = validate({"war3map.w3u": objmods.serialize(units),
                         "war3map.j": f"call SetPlayerTechResearched(Player(0), '{research}', 1)".encode()}, catalog)
    assert not [w for w in scripted["warnings"] if w["check"] == "locked_ability" and research in w["message"]]


@pytest.fixture
def scripted(tmp_path, catalog):
    """A shipped map opened as a working copy, ready for custom text triggers."""
    from wc3mcp.project.workspace import MapProject

    src = tmp_path / "checks.w3x"
    src.write_bytes(open_sample(next(m for m in sample_map_ids() if m.endswith(".w3m") or m.endswith(".w3x"))).data)
    return MapProject.open(src)


def _wrapped(name: str, body: str) -> str:
    return (f"function Trig_{name}_Actions takes nothing returns nothing\n{body}\nendfunction\n"
            f"function InitTrig_{name} takes nothing returns nothing\n"
            f"    set gg_trg_{name} = CreateTrigger()\n"
            f"    call TriggerAddAction(gg_trg_{name}, function Trig_{name}_Actions)\nendfunction\n")


def test_a_trigger_calling_a_later_triggers_function_is_an_error(scripted, catalog):
    """The script emits trigger functions in tree order, so a call into a later trigger does not compile."""
    from wc3mcp.ops.script import map_validate
    from wc3mcp.ops.triggers import triggers_edit

    triggers_edit(scripted, catalog, [
        {"op": "category", "name": "Waves"},
        {"op": "trigger", "name": "Rounds", "category": "Waves", "script": _wrapped("Rounds", "    call RR_Idx(0)")},
        {"op": "trigger", "name": "Helpers", "category": "Waves",
         "script": _wrapped("Helpers", "    call BJDebugMsg(\"x\")") +
                   "function RR_Idx takes integer i returns nothing\nendfunction\n"}])
    errors = [e for e in map_validate(scripted, catalog)["errors"] if e["check"] == "function_order"]
    assert len(errors) == 1 and "Rounds calls RR_Idx()" in errors[0]["message"]
    assert "'Helpers' defines" in errors[0]["message"] and '"index"' in errors[0]["message"]
    triggers_edit(scripted, catalog, [{"op": "trigger", "name": "Helpers", "index": 0}])
    assert [e for e in map_validate(scripted, catalog)["errors"] if e["check"] == "function_order"] == []


def test_order_strings_a_unit_will_refuse_are_warnings(scripted, catalog):
    from wc3mcp.ops.script import map_validate
    from wc3mcp.ops.triggers import triggers_edit

    triggers_edit(scripted, catalog, [{"op": "category", "name": "Casts"}, {
        "op": "trigger", "name": "Cast", "category": "Casts", "script": _wrapped("Cast", """
    call IssueImmediateOrder(udg_Hero, "slimemonster")
    call IssueImmediateOrder(udg_Hero, "summonlavaspawnnow")
    call IssuePointOrder(udg_Hero, "attack", 0, 0)""")}])
    found = {w["message"] for w in map_validate(scripted, catalog)["warnings"] if w["check"] == "order_string"}
    assert len(found) == 2
    assert any("'slimemonster' is the ability data's order of ANlm" in m and "'lavamonster'" in m for m in found)
    assert any("'summonlavaspawnnow' matches no ability order" in m for m in found)


def test_abilities_sharing_an_order_on_one_unit_are_warned_about(catalog):
    from wc3mcp.formats import objmods

    def entry(base, new, **values):
        mods = [objmods.Mod(k.encode(), objmods.INT if isinstance(v, int) else objmods.STRING, v)
                for k, v in values.items()]
        return objmods.ObjectEntry(base.encode(), new.encode(), mods)

    units, abilities = objmods.ObjectMods(3, False), objmods.ObjectMods(3, True)
    units.custom = [entry("Hamg", "H000", uabi="A000,A001,A002")]
    abilities.custom = [entry("ANcl", "A000", aord="channel"), entry("ANcl", "A001", aord="channel"),
                        entry("ANcl", "A002", aord="acidbomb")]
    result = validate({"war3map.w3u": objmods.serialize(units), "war3map.w3a": objmods.serialize(abilities)}, catalog)
    shared = [w["message"] for w in result["warnings"] if w["check"] == "ability_order"]
    assert len(shared) == 1 and shared[0].startswith("unit H000: A000, A001 all use the order 'channel'")
    abilities.custom[1] = entry("ANcl", "A001", aord="howlofterror")   # its own order: no warning
    fixed = validate({"war3map.w3u": objmods.serialize(units), "war3map.w3a": objmods.serialize(abilities)}, catalog)
    assert [w for w in fixed["warnings"] if w["check"] == "ability_order"] == []


def test_a_wall_of_trees_between_start_locations_is_a_warning(catalog):
    """A player who cannot walk to the other start is usually decoration gone wrong (a lobby platform is the
    legitimate case, so it stays a warning)."""
    from wc3mcp.formats import doo, unitsdoo, w3e

    arc = open_sample(sample_map_ids()[0])
    files = map_files(arc)
    terrain = w3e.parse(files["war3map.w3e"])
    units = unitsdoo.parse(files["war3mapUnits.doo"])
    starts = [u for u in units.units if u.id == b"sloc"]
    if len(starts) < 2:
        pytest.skip("the sample map has one start location")
    assert [w for w in validate(files, catalog)["warnings"] if w["check"] == "reachable"] == []
    trees = doo.parse(files["war3map.doo"]) if "war3map.doo" in files else doo.DoodadFile(8, 11)
    a, b = starts[0], starts[1]
    ring = [doo.Doodad(b"LTlt", 0, a.x + dx * 64, a.y + dy * 64, 0.0, 0.0, [1.0, 1.0, 1.0], b"LTlt", 2, 255)
            for dx in range(-12, 13) for dy in range(-12, 13) if max(abs(dx), abs(dy)) in (11, 12)]
    trees.doodads += ring
    files["war3map.doo"] = doo.serialize(trees)
    walled = [w["message"] for w in validate(files, catalog)["warnings"] if w["check"] == "reachable"]
    cut = {a.owner, b.owner} - {min(a.owner, b.owner)}   # the ring closes one of the two off from the other
    assert len(walled) == 1 and f"player(s) {sorted(cut)}" in walled[0] and "walkable corners" in walled[0]


# ---- hero, Channel and waygate checks ---------------------------------------------------------------------------
def _fresh(tmp_path, name="V.w3x"):
    from wc3mcp.ops.newmap import new_map

    return new_map(str(tmp_path / name), Catalog(_storage(), balance="Custom_V1"), width=64, height=64, players=2)


def _checks(project) -> set:
    from wc3mcp.ops.script import map_validate

    return {w["check"] for w in map_validate(project, Catalog(_storage(), balance="Custom_V1"))["warnings"]}


def test_hero_checks(tmp_path):
    from wc3mcp.ops.objdata import objdata_edit

    p = _fresh(tmp_path)
    c = Catalog(_storage(), balance="Custom_V1")
    objdata_edit(p, c, "unit", [{"op": "create", "base": "Hmkg", "id": "h000"},
                                {"op": "create", "base": "Hpal", "id": "H001",
                                 "set": {"uhab": "AHhb,AHds,AHre,AHad,AHhb,AHds"}}])
    assert {"hero_id_case", "hero_ability_slots"} <= _checks(p)


def test_hero_skill_points_follow_the_level_cap(tmp_path):
    from wc3mcp.ops.constants import constants_edit
    from wc3mcp.ops.objdata import objdata_edit

    p = _fresh(tmp_path)
    c = Catalog(_storage(), balance="Custom_V1")
    objdata_edit(p, c, "unit", [{"op": "create", "base": "Hpal", "id": "H000"}])
    assert "hero_skill_points" not in _checks(p)          # 3 + 3 + 3 + 1 ranks = the default cap of 10
    constants_edit(p, c, {"MaxHeroLevel": 25})
    assert "hero_skill_points" in _checks(p)


def test_a_channel_order_must_match_its_target_type(tmp_path):
    from wc3mcp.ops.objdata import objdata_edit

    p = _fresh(tmp_path)
    c = Catalog(_storage(), balance="Custom_V1")
    objdata_edit(p, c, "ability", [
        {"op": "create", "base": "ANcl", "id": "A000", "set": {"Ncl2": {"1": 0}, "Ncl6": {"1": "thunderclap"}}},
        {"op": "create", "base": "ANcl", "id": "A001", "set": {"Ncl2": {"1": 1}, "Ncl6": {"1": "impale"}}}])
    assert "channel_target" not in _checks(p)
    objdata_edit(p, c, "ability", [
        {"op": "create", "base": "ANcl", "id": "A002", "set": {"Ncl2": {"1": 0}, "Ncl6": {"1": "frostarmor"}}}])
    assert "channel_target" in _checks(p)


def test_a_waygate_into_its_own_region(tmp_path):
    from wc3mcp.ops.elements import elements_edit
    from wc3mcp.ops.placed import placed_edit

    p = _fresh(tmp_path)
    c = Catalog(_storage(), balance="Custom_V1")
    elements_edit(p, c, "region", [{"op": "upsert", "name": "Home", "left": -512, "bottom": -512, "right": 512,
                                    "top": 512}])
    placed_edit(p, c, [{"op": "add", "kind": "unit", "type": "nwgt", "x": 0, "y": 0, "owner": 27, "waygate": "Home"}])
    assert "waygate_self" in _checks(p)


def test_a_shop_item_that_is_never_in_stock_and_a_card_on_one_hotkey(tmp_path):
    from wc3mcp.ops.objdata import objdata_edit

    p = _fresh(tmp_path)
    c = Catalog(_storage(), balance="Custom_V1")
    objdata_edit(p, c, "item", [{"op": "create", "base": "rat9", "id": "I000", "set": {"isto": 0}},
                                {"op": "create", "base": "rat9", "id": "I001"}])
    objdata_edit(p, c, "unit", [{"op": "create", "base": "ngme", "id": "n000", "set": {"usei": "I000,I001"}}])
    assert {"shop_stock", "shop_hotkey"} <= _checks(p)          # both copies keep rat9's hotkey C
    objdata_edit(p, c, "item", [{"op": "set", "id": "I000", "set": {"isto": 3, "isit": 3, "istr": 1, "uhot": "Q"}}])
    assert not {"shop_stock", "shop_hotkey"} & _checks(p)


def test_an_icon_the_game_does_not_have(tmp_path):
    from wc3mcp.ops.objdata import objdata_edit

    p = _fresh(tmp_path)
    c = Catalog(_storage(), balance="Custom_V1")
    objdata_edit(p, c, "item", [{"op": "create", "base": "gcel", "id": "I000",
                                 "set": {"iico": r"ReplaceableTextures\CommandButtons\BTNGlovesOfHaste.blp"}}])
    assert "icon" in _checks(p)
    objdata_edit(p, c, "item", [{"op": "set", "id": "I000",
                                 "set": {"iico": r"ReplaceableTextures\CommandButtons\BTNGlove.blp"}}])
    assert "icon" not in _checks(p)


def test_a_channel_on_an_order_the_game_does_not_know(tmp_path):
    from wc3mcp.ops.objdata import objdata_edit

    p = _fresh(tmp_path)
    c = Catalog(_storage(), balance="Custom_V1")
    objdata_edit(p, c, "ability", [{"op": "create", "base": "ANcl", "id": "A000", "set": {"Ncl6": {"1": "warcry"}}}])
    assert "channel_order" not in _checks(p)                  # unbacked, but it resolved and cast in a game run
    objdata_edit(p, c, "ability", [{"op": "create", "base": "ANcl", "id": "A001",
                                    "set": {"Ncl6": {"1": "holywrath"}}}])
    assert "channel_order" in _checks(p)                      # OrderId("holywrath") is 0 in the game


def test_a_channel_whose_middle_ranks_have_no_button(tmp_path):
    from wc3mcp.ops.objdata import objdata_edit

    p = _fresh(tmp_path)
    c = Catalog(_storage(), balance="Custom_V1")
    out = objdata_edit(p, c, "ability", [{"op": "create", "base": "ANcl", "id": "A000",
                                          "set": {"Ncl3": {"1": 1}, "alev": 6}}])
    assert any("rank(s) 2-3" in w for w in out["warnings"])          # Channel's own Ncl3 is 0 at ranks 2 and 3
    assert "channel_levels" in _checks(p)
    objdata_edit(p, c, "ability", [{"op": "set", "id": "A000", "set": {"Ncl3": [1, 1, 1, 1, 1, 1]}}])
    assert "channel_levels" not in _checks(p)
