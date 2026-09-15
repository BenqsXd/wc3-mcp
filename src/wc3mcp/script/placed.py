"""Editor-generated script parts for placed objects and map random tables: InitRandomGroups, ItemTable/Unit/Doodad
drop-item functions, CreateAllDestructables, CreateAllItems and the Unit Creation functions, with their gg_unit_ /
gg_item_ / gg_dest_ / gg_rg_ globals. Exact on the local JASS corpus (461 of 462 maps; the other has no units)."""
import math
import re
import struct
from dataclasses import dataclass
from typing import Callable

from ..formats import doo, unitsdoo, w3i, w3r, wct, wtg
from ..ops.gui import script_name
from ..ops.triggers import _all_params, _triggers

BAR = "//" + "=" * 75
BANNER = "//" + "*" * 75
F32_DEG = struct.unpack("<f", struct.pack("<f", 180 / math.pi))[0]
NO_ID = b"\0\0\0\0"
NEUTRAL = {24: "PLAYER_NEUTRAL_AGGRESSIVE", 27: "PLAYER_NEUTRAL_PASSIVE"}
UNIT_LOCALS = ["    local unit u", "    local integer unitID", "    local trigger t", "    local real life", ""]
ITEM_CLASS = {"i": "ITEM_TYPE_PERMANENT", "j": "ITEM_TYPE_CHARGED", "k": "ITEM_TYPE_POWERUP", "l": "ITEM_TYPE_ARTIFACT",
              "m": "ITEM_TYPE_PURCHASABLE", "n": "ITEM_TYPE_CAMPAIGN", "o": "ITEM_TYPE_MISCELLANEOUS"}
REFERENCE = re.compile(r"gg_(?:unit|item|dest)_\w{4}_\d{4}")
TITLES = ("Random Groups", "Map Item Tables", "Unit Item Tables", "Destructible Item Tables", "Destructable Objects",
          "Items", "Unit Creation")
MAIN_CALLS = ("CreateAllDestructables", "CreateAllItems", "InitRandomGroups", "CreateAllUnits")
_DESTRUCTABLE = re.compile(r"Create\w*Destructable\w*\( '(\w{4})', ([-\d.]+), ([-\d.]+),")
_ITEM = re.compile(r"BlzCreateItemWithSkin\( '(\w{4})', ([-\d.]+), ([-\d.]+),")


@dataclass
class Placed:
    units: unitsdoo.UnitFile | None
    doodads: doo.DoodadFile | None
    info: w3i.MapInfo | None
    regions: w3r.RegionFile | None
    unit: Callable[[str], dict | None]  # {building, abilities, team_color}; None for items and start locations
    ability: Callable[[str], dict]  # {hero, order, orderon, orderoff}
    destructible: Callable[[str], dict | None]  # {team_color, vertex: (r, g, b)}; None for doodads
    item: Callable[[str], dict | None]  # {team_color}; None for units


def _id(raw: bytes) -> str:
    return raw.decode("latin-1")


def _f1(v: float) -> str:
    return f"{v:.1f}"


def _facing(radians: float) -> str:
    return f"{struct.unpack('<f', struct.pack('<f', radians * F32_DEG))[0]:.3f}"


def _lines(lines: list[str]) -> str:
    return "".join(x + "\n" for x in lines)


def _banner(title: str) -> str:
    return f"{BANNER}\n//*\n//*  {title}\n//*\n{BANNER}\n\n"


def references(tf: wtg.TriggerFile, ct: wct.CustomText) -> tuple[set[str], set[str]]:
    """(names declared as globals: used anywhere in triggers, names given to created objects: used by enabled GUI
    code or any custom script)"""
    texts = set(REFERENCE.findall("\n".join([*(x or "" for x in ct.texts), ct.header or ""])))
    declared, named = set(texts), set(texts)
    for t in _triggers(tf):
        for values, only_enabled in ((declared, False), (named, True)):
            if only_enabled and not t.enabled:
                continue
            values |= {p.value for p in _all_params(t.ecas, only_enabled)
                       if isinstance(p.value, str) and REFERENCE.fullmatch(p.value)}
    return declared, named


# ---- drop tables -------------------------------------------------------------------------------------------------
def random_item_style(script: str) -> str:
    """How the script's editor spelled random items: "filter" (current editor, also for scripts without any),
    "any" or "plain" (older editors: ChooseRandomItemEx, with ITEM_TYPE_ANY or ChooseRandomItem for any class)."""
    if "ChooseRandomItemExWithFilter(" in script or not re.search(r"ChooseRandomItem(?:Ex)?\(", script):
        return "filter"
    return "any" if "ITEM_TYPE_ANY" in script else "plain"


def _item_expr(raw: bytes, style: str) -> str:
    t = _id(raw)
    if raw == NO_ID:
        return "-1"
    if t[0] == "Y" and t[2] == "I" and t[3].isdigit() and (t[1] == "Y" or t[1] in ITEM_CLASS):
        kind = "ITEM_TYPE_ANY" if t[1] == "Y" else ITEM_CLASS[t[1]]
        if style == "filter":
            return f"ChooseRandomItemExWithFilter( {kind}, {t[3]}, EQUIPMENT_TYPE_ANY, ITEMTAG_TYPE_ANY)"
        if t[1] == "Y" and style == "plain":
            return f"ChooseRandomItem( {t[3]} )"
        return f"ChooseRandomItemEx( {kind}, {t[3]} )"
    return f"'{t}'"


def _drop_function(name: str, sets: list, style: str) -> str:
    lines = ["    local widget  trigWidget = null", "    local unit    trigUnit   = null",
             "    local integer itemID     = 0", "    local boolean canDrop    = true", "",
             "    set trigWidget = bj_lastDyingWidget", "    if (trigWidget == null) then",
             "        set trigUnit = GetTriggerUnit()", "    endif", "",
             "    if (trigUnit != null) then", "        set canDrop = not IsUnitHidden(trigUnit)",
             "        if (canDrop and GetChangingUnit() != null) then",
             "            set canDrop = (GetChangingUnitPrevOwner() == Player(PLAYER_NEUTRAL_AGGRESSIVE))",
             "        endif", "    endif", "", "    if (canDrop) then"]
    for k, entries in enumerate(sets):
        lines += [f"        // Item set {k}", "        call RandomDistReset(  )"]
        lines += [f"        call RandomDistAddItem( {_item_expr(item, style)}, {chance} )" for item, chance in entries]
        rest = 100 - sum(chance for _, chance in entries)
        if rest > 0:
            lines.append(f"        call RandomDistAddItem( -1, {rest} )")
        lines += ["        set itemID = RandomDistChoose(  )", "        if (trigUnit != null) then",
                  "            call UnitDropItem( trigUnit, itemID )", "        else",
                  "            call WidgetDropItem( trigWidget, itemID )", "        endif", ""]
    lines += ["    endif", "", "    set bj_lastDyingWidget = null", "    call DestroyTrigger(GetTriggeringTrigger())"]
    return f"function {name} takes nothing returns nothing\n" + _lines(lines) + "endfunction\n\n"


# ---- sections ----------------------------------------------------------------------------------------------------
class _Gen:
    def __init__(self, p: Placed, script: str, named: set[str]):
        self.p, self.named = p, named
        self.item_style = random_item_style(script)
        self.groups = [t.id for t in p.info.random_unit_tables] if p.info else []
        self.region_names = {g.index: "gg_rct_" + script_name(g.name) for g in (p.regions.regions if p.regions else [])}
        self.previous = {}  # objects already created by the script keep their order within their type
        for fn, kind, pattern in (("CreateAllDestructables", "dest", _DESTRUCTABLE), ("CreateAllItems", "item", _ITEM)):
            m = re.search(r"^function %s takes nothing returns nothing\r?\n(.*?)^endfunction" % fn, script, re.S | re.M)
            for k, c in enumerate(pattern.finditer(m.group(1) if m else "")):
                self.previous.setdefault((kind, *c.groups()), k)

    def _order(self, kind: str, objs: list) -> list:
        return sorted(objs, key=lambda e: (_id(e[1].id), self.previous.get((kind, _id(e[1].id), _f1(e[1].x),
                                                                              _f1(e[1].y)), 1 << 30), e[1].editor_id, e[0]))

    def random_groups(self) -> str | None:
        tables = self.p.info.random_unit_tables if self.p.info else []
        if not tables:
            return None
        lines = ["    local integer curset", ""]
        for k, t in enumerate(tables):
            lines += [f"    // Group {k} - {t.name}", "    call RandomDistReset(  )"]
            lines += [f"    call RandomDistAddItem( {j}, {chance} )" for j, (chance, _) in enumerate(t.lines)]
            lines += ["    set curset = RandomDistChoose(  )", ""]
            for j, (_, ids) in enumerate(t.lines):
                lines.append(f"    {'if' if j == 0 else 'elseif'} (curset == {j}) then")
                lines += [f"        set gg_rg_{k:03d}[{pos}] = " + ("-1" if unit == NO_ID else f"'{_id(unit)}'")
                          for pos, unit in enumerate(ids)]
            lines.append("    else")
            lines += [f"        set gg_rg_{k:03d}[{pos}] = -1" for pos in range(len(t.positions))]
            lines += ["    endif", ""]
        return _banner("Random Groups") + "function InitRandomGroups takes nothing returns nothing\n" + _lines(lines) \
            + "endfunction\n\n"

    def map_item_tables(self) -> str | None:
        tables = self.p.info.random_item_tables if self.p.info else []
        if not tables:
            return None
        return _banner("Map Item Tables") + "".join(
            _drop_function(f"ItemTable{t.id:06d}_DropItems", [[(i, c) for c, i in s] for s in t.sets], self.item_style)
            for t in tables) + "\n"

    def unit_item_tables(self) -> str | None:
        body = "".join(_drop_function(f"Unit{i:06d}_DropItems", u.item_sets, self.item_style)
                       for i, u in enumerate(self.p.units.units if self.p.units else [])
                       if u.item_table < 0 and any(u.item_sets))
        return _banner("Unit Item Tables") + body + "\n" if body else None

    def destructible_item_tables(self) -> str | None:
        body = "".join(_drop_function(f"Doodad{i:06d}_DropItems", d.item_sets, self.item_style)
                       for i, d in enumerate(self.p.doodads.doodads if self.p.doodads else [])
                       if d.item_table < 0 and any(d.item_sets) and self.p.destructible(_id(d.id)) is not None)
        return _banner("Destructible Item Tables") + body + "\n" if body else None

    def destructables(self) -> str | None:
        df = self.p.doodads
        objs = []
        for i, d in enumerate(df.doodads if df else []):
            info = self.p.destructible(_id(d.id))
            name = f"gg_dest_{_id(d.id)}_{d.editor_id:04d}"
            if info is not None and (name in self.named or d.item_table >= 0 or any(d.item_sets)):
                objs.append((i, d, name if name in self.named else "d", info))
        if not objs:
            return None
        lines = ["    local destructable d", "    local trigger t", "    local real life"]
        for i, d, var, info in self._order("dest", objs):
            t, dead, fixed = _id(d.id), "Dead" if d.life == 0 else "", "Z" if d.flags & 4 else ""
            z = f"{_f1(d.z)}, " if fixed else ""
            args = f"'{t}', {_f1(d.x)}, {_f1(d.y)}, {z}{_facing(d.angle)}"
            if df.version >= 12:
                color = f", ConvertPlayerColor({info['team_color']})" if df.version >= 13 else ""
                lines.append(f"    set {var} = BlzCreate{dead}Destructable{fixed}WithSkinPitchRoll"
                             f"{'Color' if color else ''}( {args}, 0.000, 0.000, {d.scale[0]:.3f}, {d.variation}, "
                             f"'{_id(d.skin)}'{color} )")
                if color:
                    lines.append(f"    call SetDestructableVertexColor( {var}, {', '.join(map(str, info['vertex']))}, 255 )")
            else:
                lines.append(f"    set {var} = BlzCreate{dead}Destructable{fixed}WithSkin( {args}, {d.scale[0]:.3f}, "
                             f"{d.variation}, '{_id(d.skin)}' )")
            if 0 < d.life < 100:
                lines += [f"    set life = GetDestructableLife( {var} )",
                          f"    call SetDestructableLife( {var}, {d.life / 100:.2f} * life )"]
            if d.item_table >= 0 or any(d.item_sets):
                fn = f"ItemTable{d.item_table:06d}" if d.item_table >= 0 else f"Doodad{i:06d}"
                lines += ["    set t = CreateTrigger(  )", f"    call TriggerRegisterDeathEvent( t, {var} )",
                          "    call TriggerAddAction( t, function SaveDyingWidget )",
                          f"    call TriggerAddAction( t, function {fn}_DropItems )"]
        return _banner("Destructable Objects") + "function CreateAllDestructables takes nothing returns nothing\n" \
            + _lines(lines) + "endfunction\n\n"

    def items(self) -> str | None:
        uf = self.p.units
        objs = [(i, u, self.p.item(_id(u.id))) for i, u in enumerate(uf.units if uf else [])]
        objs = [(i, u, info) for i, u, info in objs if info is not None]
        if not objs:
            return None
        colored = uf.version >= 13
        lines = ["    local integer itemID"] + (["    local item i"] if colored else []) + [""]
        for i, u, info in self._order("item", objs):
            t = _id(u.id)
            name = f"gg_item_{t}_{u.editor_id:04d}"
            create = f"BlzCreateItemWithSkin( '{t}', {_f1(u.x)}, {_f1(u.y)}, '{_id(u.skin)}' )"
            var = name if name in self.named else "i" if colored else None
            lines.append(f"    set {var} = {create}" if var else f"    call {create}")
            if colored:
                lines.append(f"    call SetItemColor( {var}, ConvertPlayerColor({u.color if u.color >= 0 else info['team_color']}) )")
        return _banner("Items") + "function CreateAllItems takes nothing returns nothing\n" + _lines(lines) \
            + "endfunction\n\n"

    def _unit(self, u: unitsdoo.Unit, index: int, info: dict) -> list[str]:
        t = _id(u.id)
        name = f"gg_unit_{t}_{u.editor_id:04d}"
        var = name if name in self.named else "u"
        at = f"{_f1(u.x)}, {_f1(u.y)}, {_facing(u.angle)}"
        out, ind = [], "    "
        if t in ("uDNR", "bDNR") and u.random_flag in (0, 1, 2):
            if u.random_flag == 1:
                group = int.from_bytes(u.random_data[:4], "little", signed=True)
                position = int.from_bytes(u.random_data[4:], "little", signed=True)
                k = self.groups.index(group) if group in self.groups else group
                out.append(f"    set unitID = gg_rg_{k:03d}[{position}]")
            elif u.random_flag == 2:
                out.append("    call RandomDistReset(  )")
                out += [f"    call RandomDistAddItem( '{_id(i)}', {c} )" for i, c in u.random_units]
                out.append("    set unitID = RandomDistChoose(  )")
            else:
                # ponytail: level-based random units are not in the local corpus; this is the common.j equivalent
                level = int.from_bytes(u.random_data[:3], "little", signed=True)
                fn = "ChooseRandomNPBuilding(  )" if t == "bDNR" else f"ChooseRandomCreep( {level} )"
                out.append(f"    set unitID = {fn}")
            out += ["    if (unitID != -1) then", f"        set {var} = BlzCreateUnitWithSkin( p, unitID, {at}, unitID )"]
            ind = "        "
        elif t == "ugol":
            out.append(f"    set {var} = CreateBlightedGoldmine( p, {at} )")
        else:
            out.append(f"    set {var} = BlzCreateUnitWithSkin( p, '{t}', {at}, '{_id(u.skin)}' )")
        if u.hero_level > 1:
            out.append(f"{ind}call SetHeroLevel( {var}, {u.hero_level}, false )")
        if u.hp >= 0:
            out += [f"{ind}set life = GetUnitState( {var}, UNIT_STATE_LIFE )",
                    f"{ind}call SetUnitState( {var}, UNIT_STATE_LIFE, {u.hp / 100:.2f} * life )"]
        if u.mp >= 0:
            out.append(f"{ind}call SetUnitState( {var}, UNIT_STATE_MANA, {u.mp} )")
        if "Agld" in info["abilities"] or "Abgm" in info["abilities"]:
            out.append(f"{ind}call SetResourceAmount( {var}, {u.gold} )")
        if u.target_acquisition == -2:
            out.append(f"{ind}call SetUnitAcquireRange( {var}, 200.0 )")
        elif u.target_acquisition >= 0:
            out.append(f"{ind}call SetUnitAcquireRange( {var}, {_f1(u.target_acquisition)} )")
        for ability, autocast, level in u.abilities:
            a = self.p.ability(_id(ability))
            if a["hero"]:
                out += [f"{ind}call SelectHeroSkill( {var}, '{_id(ability)}' )"] * level
                if level == 0:
                    continue
            order = (a["orderon"] if autocast else a["orderoff"]) if a["orderon"] or a["orderoff"] else \
                a["order"] if autocast else None
            if order:
                out.append(f'{ind}call IssueImmediateOrder( {var}, "{order}" )')
        out += [f"{ind}call UnitAddItemToSlotById( {var}, '{_id(item)}', {slot} )" for slot, item in u.inventory]
        if u.waygate >= 0 and "Awrp" in info["abilities"] and u.waygate in self.region_names:
            r = self.region_names[u.waygate]
            out += [f"{ind}call WaygateSetDestination( {var}, GetRectCenterX({r}), GetRectCenterY({r}) )",
                    f"{ind}call WaygateActivate( {var}, true )"]
        color = u.color if u.color >= 0 and "Awrp" in info["abilities"] else info["team_color"]
        if color >= 0:
            out.append(f"{ind}call SetUnitColor( {var}, ConvertPlayerColor({color}) )")
        if (u.owner >> 16) & 1:
            out.append(f'{ind}call IssueImmediateOrder( {var}, "unroot" )')
        if u.item_table >= 0 or any(u.item_sets):
            fn = f"ItemTable{u.item_table:06d}" if u.item_table >= 0 else f"Unit{index:06d}"
            out += [f"{ind}set t = CreateTrigger(  )", f"{ind}call TriggerRegisterUnitEvent( t, {var}, EVENT_UNIT_DEATH )",
                    f"{ind}call TriggerRegisterUnitEvent( t, {var}, EVENT_UNIT_CHANGE_OWNER )",
                    f"{ind}call TriggerAddAction( t, function {fn}_DropItems )"]
        if ind != "    ":
            out.append("    endif")
        return out

    def unit_creation(self) -> str | None:
        groups: dict[tuple[int, bool], list] = {}
        for index, u in enumerate(self.p.units.units if self.p.units else []):
            info = None if u.id == b"sloc" else self.p.unit(_id(u.id))
            if info is not None:
                groups.setdefault((u.owner & 0xFFFF, bool(info["building"])), []).append((u.editor_id, index, u, info))
        if not groups:
            return None
        fns = {}
        for (owner, building), units in groups.items():
            if owner in NEUTRAL:
                name = ("CreateNeutralHostile" if owner == 24 else "CreateNeutralPassive") + ("Buildings" if building else "")
            else:
                name = f"Create{'Buildings' if building else 'Units'}ForPlayer{owner}"
            lines = [f"    local player p = Player({NEUTRAL.get(owner, owner)})", *UNIT_LOCALS]
            for _, index, u, info in sorted(units, key=lambda e: (e[0], e[1])):
                lines += self._unit(u, index, info)
            fns[name] = lines
        players = sorted({owner for owner, _ in groups if owner not in NEUTRAL})
        buildings = [f"CreateBuildingsForPlayer{p}" for p in players if f"CreateBuildingsForPlayer{p}" in fns]
        units = [f"CreateUnitsForPlayer{p}" for p in players if f"CreateUnitsForPlayer{p}" in fns]
        order = [n for p in players for n in (f"CreateBuildingsForPlayer{p}", f"CreateUnitsForPlayer{p}") if n in fns]
        order += [n for n in ("CreateNeutralHostileBuildings", "CreateNeutralHostile", "CreateNeutralPassiveBuildings",
                              "CreateNeutralPassive") if n in fns]
        fns["CreatePlayerBuildings"] = [f"    call {n}(  )" for n in buildings]
        fns["CreatePlayerUnits"] = [f"    call {n}(  )" for n in units]
        fns["CreateAllUnits"] = [f"    call {n}(  )" for n in (
            "CreateNeutralHostileBuildings", "CreateNeutralPassiveBuildings", "CreatePlayerBuildings",
            "CreateNeutralHostile", "CreateNeutralPassive", "CreatePlayerUnits")
            if n in fns]
        return _banner("Unit Creation") + "".join(
            f"{BAR}\nfunction {n} takes nothing returns nothing\n{_lines(fns[n])}endfunction\n\n"
            for n in order + ["CreatePlayerBuildings", "CreatePlayerUnits", "CreateAllUnits"])

    def global_decls(self, declared: set[str]) -> list[tuple[str, str]]:
        """(JASS type, name) of existing objects that triggers use: Units.doo order, then war3map.doo"""
        out = []
        for u in self.p.units.units if self.p.units else []:
            name = f"gg_unit_{_id(u.id)}_{u.editor_id:04d}"
            if self.p.item(_id(u.id)) is not None:
                name = f"gg_item_{_id(u.id)}_{u.editor_id:04d}"
            if name in declared:
                out.append(("item" if name.startswith("gg_item_") else "unit", name))
        for d in self.p.doodads.doodads if self.p.doodads else []:
            name = f"gg_dest_{_id(d.id)}_{d.editor_id:04d}"
            if name in declared:
                out.append(("destructable", name))
        return list({name: (jt, name) for jt, name in out}.values())  # a name appears once, first position wins


def sections(p: Placed, script: str, tf: wtg.TriggerFile, ct: wct.CustomText) -> dict:
    """Section texts by title (None when absent), `globals` [(type, name)], `random_groups` count and `main` calls."""
    declared, named = references(tf, ct)
    g = _Gen(p, script, named)
    out = {"Random Groups": g.random_groups(), "Map Item Tables": g.map_item_tables(),
           "Unit Item Tables": g.unit_item_tables(), "Destructible Item Tables": g.destructible_item_tables(),
           "Destructable Objects": g.destructables(), "Items": g.items(), "Unit Creation": g.unit_creation()}
    out["globals"] = g.global_decls(declared)
    out["random_groups"] = len(g.groups)
    out["main"] = [fn for fn, title in zip(MAIN_CALLS, ("Destructable Objects", "Items", "Random Groups", "Unit Creation"))
                   if out[title]]
    return out
