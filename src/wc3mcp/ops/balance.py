"""What a custom object is actually worth: damage per second, effective hit points and what those cost in gold, read
straight out of the object data and set beside the stock objects of the same price. A unit that out-damages a Knight
for half the gold is a defect you can see here without launching the game.

Every number says which fields it came from, so a reader can check it instead of trusting it.
"""
import statistics

from ..errors import ToolError
from . import constants as constants_ops
from .objdata import _entries, _load, _merged, objdata_get, objdata_list

# attack fields, per weapon index: cooldown, base damage, dice, sides, range, targets, weapon type
ATTACK = {1: ("ua1c", "ua1b", "ua1d", "ua1s", "ua1r", "ua1g", "ua1w"),
          2: ("ua2c", "ua2b", "ua2d", "ua2s", "ua2r", "ua2g", "ua2w")}
ATTACKS_ENABLED = "uaen"      # 0 none, 1 first, 2 second, 3 both
DEFENCE, LIFE, MANA = "udef", "uhpm", "umpm"
COST = ("ugol", "ulum", "ufoo")
SPEED, SIGHT, BUILD = "umvs", "usid", "ubld"
# the armour formula the game uses for positive armour; negative armour adds damage instead
ARMOUR_STEP = 0.06
ITEM_BONUS = {"Iagi": "agility", "Iint": "intelligence", "Istr": "strength", "Iatt": "damage", "Ilif": "life",
              "Iman": "mana", "Idef": "armour", "Ihpr": "life regeneration", "Imrp": "mana regeneration",
              "Isx1": "attack speed", "Ocr1": "critical chance", "Ocr2": "critical multiplier"}
ABILITY_FIELDS = {"acdn": "cooldown", "amcs": "mana cost", "aran": "cast range", "adur": "duration",
                  "ahdu": "hero duration", "aare": "area"}
STOCK_UNITS = ("hfoo", "hkni", "hrif", "hmpr", "hsor", "ofoo", "ogru", "orai", "otau", "ohun", "uzom", "ucry",
               "uabo", "ufro", "eary", "esen", "edry", "edoc", "ebal", "hpea", "opeo", "uaco", "ewsp")
STOCK_ITEMS = ("rst1", "rag1", "rin1", "ratc", "rde2", "prvt", "rlif", "penr", "rwiz", "gcel", "ciri", "ckng")
# a hero is only comparable with heroes: its unit fields say life 100 and damage 2 whatever it is worth
STOCK_HEROES = ("Hamg", "Hmkg", "Hpal", "Hblm", "Obla", "Ofar", "Otch", "Oshd", "Udea", "Udre", "Ulic", "Ucrl",
                "Ekee", "Emoo", "Ewar", "Edem")


def _number(value, default: float = 0.0) -> float:
    if isinstance(value, list):
        value = value[0] if value else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fields(project, catalog, kind: str, obj_id: str) -> tuple[dict, dict]:
    """Every field of one object as the editor sees it, raw code -> value, or the list of its per-level values."""
    doc = objdata_get(project, catalog, kind, obj_id)
    out = {}
    for rawcode, entry in doc["fields"].items():
        out[rawcode] = entry["values"] if "values" in entry else entry.get("value")
    return out, doc


def _first(value):
    """A field's value, or the first level of a per-level one, which is what a unit or an item reads."""
    return value[0] if isinstance(value, list) else value


def _level(fields: dict, rawcode: str, level: int):
    """One level of a per-level field; a field without levels answers with its single value."""
    value = fields.get(rawcode)
    if isinstance(value, list):
        return value[min(level, len(value)) - 1] if value else None
    return value


def _attack(fields: dict, index: int) -> dict | None:
    cooldown, base, dice, sides, reach, targets, weapon = (fields.get(f) for f in ATTACK[index])
    cool = _number(cooldown)
    average = _number(base) + _number(dice) * (_number(sides) + 1) / 2
    if cool <= 0 or average <= 0:
        return None
    return {"average_damage": round(average, 2), "cooldown": round(cool, 2),
            "damage_per_second": round(average / cool, 2), "range": _number(reach),
            "targets": targets, "weapon": weapon}


def _attributes(fields: dict, level: int) -> dict:
    """A hero's three attributes at a level: the starting value plus the per-level gain."""
    return {name: _number(fields.get(start)) + _number(fields.get(gain)) * (level - 1)
            for name, start, gain in (("strength", "ustr", "ustp"), ("agility", "uagi", "uagp"),
                                      ("intelligence", "uint", "uinp"))}


def _hero(fields: dict, misc: dict, level: int) -> dict:
    """What a hero actually has at a level. Its unit fields say life 100 and damage 2: the attributes carry the rest,
    through the gameplay constants (StrHitPointBonus and friends), so reading the fields alone is misleading."""
    attributes = _attributes(fields, level)
    primary = {"STR": "strength", "AGI": "agility", "INT": "intelligence"}.get(str(fields.get("upra") or "").upper())
    bonus = attributes.get(primary, 0.0) * _number(misc.get("StrAttackBonus"), 1.0)
    life = _number(fields.get(LIFE)) + attributes["strength"] * _number(misc.get("StrHitPointBonus"), 25.0)
    mana = _number(fields.get(MANA)) + attributes["intelligence"] * _number(misc.get("IntManaBonus"), 15.0)
    armour = (_number(fields.get(DEFENCE)) + _number(misc.get("AgiDefenseBase"), -2.0)
              + attributes["agility"] * _number(misc.get("AgiDefenseBonus"), 0.3))
    speed = 1 + attributes["agility"] * _number(misc.get("AgiAttackSpeedBonus"), 0.02)
    out = {"level": level, "attributes": {k: round(v, 1) for k, v in attributes.items()},
           "primary_attribute": primary, "attack_damage_bonus": round(bonus, 1),
           "life": round(life), "mana": round(mana), "armour": round(armour, 1),
           "attack_speed_factor": round(speed, 2)}
    attack = _attack(fields, 1)
    if attack:
        out["damage_per_second"] = round((attack["average_damage"] + bonus) / attack["cooldown"] * speed, 2)
    return out


def _unit(fields: dict, misc: dict | None = None, top_level: int = 10) -> dict:
    """Damage per second, effective hit points and the cost ratios of one unit. A hero also gets what its attributes
    and the gameplay constants make of those numbers, at level 1 and at the level cap."""
    enabled = int(_number(fields.get(ATTACKS_ENABLED), 0))
    attacks = {}
    for index in (1, 2):
        if enabled & index or (enabled == 0 and index == 1 and _number(fields.get("ua1c")) > 0):
            found = _attack(fields, index)
            if found:
                attacks[f"attack{index}"] = found
    dps = round(sum(a["damage_per_second"] for a in attacks.values()), 2)
    life = _number(fields.get(LIFE))
    armour = _number(fields.get(DEFENCE))
    # positive armour reduces damage by 6% per point, with diminishing returns; negative armour raises it
    reduction = ARMOUR_STEP * armour / (1 + ARMOUR_STEP * armour) if armour >= 0 else ARMOUR_STEP * armour
    effective = life / (1 - reduction) if reduction < 1 else life
    gold, lumber, food = (_number(fields.get(f)) for f in COST)
    worth = gold + lumber
    out = {"damage_per_second": dps, "attacks": attacks, "life": life, "armour": armour,
           "effective_life": round(effective), "mana": _number(fields.get(MANA)),
           "gold": gold, "lumber": lumber, "food": food,
           "speed": _number(fields.get(SPEED)), "sight": _number(fields.get(SIGHT)),
           "build_time": _number(fields.get(BUILD))}
    if worth > 0:
        out["damage_per_gold"] = round(dps / worth * 100, 2)
        out["life_per_gold"] = round(effective / worth * 100, 2)
        # one number to sort by: damage and staying power together, per 100 gold
        out["worth"] = round((dps * effective) ** 0.5 / worth * 100, 2)
    out["read"] = "ua1c/ua1b/ua1d/ua1s (and ua2*), uaen, uhpm, udef, umpm, ugol, ulum, ufoo, umvs, usid, ubld"
    if misc is not None and str(fields.get("udty") or "").lower() == "hero":
        levels = [_hero(fields, misc, 1)] + ([_hero(fields, misc, top_level)] if top_level > 1 else [])
        out["hero"] = {"level_cap": top_level, "levels": levels,
                       "read": "udty, upra, ustr/ustp, uagi/uagp, uint/uinp and the gameplay constants "
                               "StrHitPointBonus, IntManaBonus, AgiDefenseBase/Bonus, AgiAttackSpeedBonus, "
                               "StrAttackBonus (constants_get)"}
        # the unit fields of every hero read life 100, damage 2 and mana 0: compare the attribute numbers instead
        out["life"], out["mana"] = levels[0]["life"], levels[0]["mana"]
        out["armour"] = levels[0]["armour"]
        if "damage_per_second" in levels[0]:
            out["damage_per_second"] = levels[0]["damage_per_second"]
        reduction = ARMOUR_STEP * out["armour"] / (1 + ARMOUR_STEP * out["armour"]) if out["armour"] >= 0 \
            else ARMOUR_STEP * out["armour"]
        out["effective_life"] = round(out["life"] / (1 - reduction) if reduction < 1 else out["life"])
        if worth > 0:   # the ratios follow the hero's real numbers, not the 100 life every hero has on paper
            out["damage_per_gold"] = round(out["damage_per_second"] / worth * 100, 2)
            out["life_per_gold"] = round(out["effective_life"] / worth * 100, 2)
            out["worth"] = round((out["damage_per_second"] * out["effective_life"]) ** 0.5 / worth * 100, 2)
    return out


def _item(fields: dict, catalog, project) -> dict:
    """The bonuses an item's abilities give, and what they cost in gold."""
    bonuses, abilities = {}, [a for a in str(fields.get("iabi") or "").split(",") if a.strip()]
    for ability in abilities:
        try:
            values, _doc = _fields(project, catalog, "ability", ability)
        except ToolError:
            continue
        for rawcode, name in ITEM_BONUS.items():
            value = _number(_first(values.get(rawcode)))
            if value:
                bonuses[name] = round(bonuses.get(name, 0.0) + value, 2)
    gold = _number(fields.get("igol"))
    out = {"abilities": abilities, "bonuses": bonuses, "gold": gold, "level": _number(fields.get("ilev")),
           "read": "iabi, igol, ilev and the bonus fields of each ability (" + ", ".join(sorted(ITEM_BONUS)) + ")"}
    if gold > 0 and bonuses:
        out["bonus_per_100_gold"] = {name: round(value / gold * 100, 2) for name, value in bonuses.items()}
    return out


def _ability(fields: dict, levels: int) -> dict:
    """The per-level curve of an ability, and what its damage costs in mana and in cooldown."""
    rows = []
    for level in range(1, levels + 1):
        row = {"level": level}
        for rawcode, name in ABILITY_FIELDS.items():
            value = _level(fields, rawcode, level)
            if value is not None:
                row[name] = _number(value)
        damage = 0.0
        for guess in ("Hbz1", "Uan1", "Ocl1", "Ebl1", "Idam", "Hca1"):
            damage = damage or _number(_level(fields, guess, level))
        if damage:
            row["damage"] = damage
            if row.get("mana cost"):
                row["damage_per_mana"] = round(damage / row["mana cost"], 2)
            if row.get("cooldown"):
                row["damage_per_second_of_cooldown"] = round(damage / row["cooldown"], 2)
        rows.append(row)
    return {"levels": rows, "read": "acdn, amcs, aran, adur, ahdu, aare and the first data field that holds damage"}


def _stock(project, catalog, kind: str, ids, misc: dict | None = None, top_level: int = 10) -> list[dict]:
    out = []
    for stock in ids:
        try:
            fields, doc = _fields(project, catalog, kind, stock)
        except ToolError:
            continue
        row = _unit(fields, misc, top_level) if kind == "unit" else _item(fields, catalog, project)
        out.append({"id": stock, "name": doc.get("name", stock), **row})
    return out


def _closest(row: dict, stock: list[dict], kind: str) -> list[dict]:
    """The stock objects nearest in price (and, for a unit, in food), which is the only fair yardstick."""
    if kind == "unit":
        def distance(other):
            return (abs(other["food"] - row["food"]) * 200 + abs(other["gold"] + other["lumber"]
                                                                 - row["gold"] - row["lumber"]))
    else:
        def distance(other):
            return abs(other["gold"] - row["gold"])
    return sorted((s for s in stock if s.get("gold", 0) > 0), key=distance)[:3]


def _flag(row: dict, near: list[dict], kind: str) -> list[str]:
    """Where the object is far outside what the nearest stock objects show. No verdict the numbers do not support."""
    notes = []
    if kind == "unit":
        for key, label in (("damage_per_gold", "damage per gold"), ("life_per_gold", "effective life per gold")):
            mine, theirs = row.get(key), [s[key] for s in near if s.get(key)]
            if mine and theirs:
                median = statistics.median(theirs)
                if median and mine > median * 1.5:
                    notes.append(f"{label} is {mine / median:.1f}x the median of {', '.join(s['id'] for s in near)}")
                elif median and mine < median * 0.5:
                    notes.append(f"{label} is {mine / median:.1f}x that median, so it is poor value")
    else:
        mine = sum(row.get("bonus_per_100_gold", {}).values())
        theirs = [sum(s.get("bonus_per_100_gold", {}).values()) for s in near if s.get("bonus_per_100_gold")]
        if mine and theirs:
            median = statistics.median(theirs)
            if median and mine > median * 1.5:
                notes.append(f"its bonuses per 100 gold are {mine / median:.1f}x the median of "
                             f"{', '.join(s['id'] for s in near)}")
    return notes


def button_cells(project, catalog, ids: list[str]) -> dict[str, list[str]]:
    """Command-card cells (abpx, abpy) two or more of these abilities share, over every id given - the row limit of
    the report does not apply, because an absent cell reads as "no collision"."""
    main, skin, _ = _load(project, "ability")
    cells: dict[str, list[str]] = {}
    for obj_id in ids:
        entries = _entries((main, skin), obj_id)
        base = entries[0][2].base_id.decode("latin-1") if entries else obj_id
        mods = _merged(entries)
        cell = []
        for rid in ("abpx", "abpy"):
            mod = mods.get((rid, 0)) or mods.get((rid, 1))
            cell.append(mod.value if mod is not None else catalog.field("ability", base, rid))
        if None not in cell and "" not in cell:
            cells.setdefault(f"{int(float(cell[0]))},{int(float(cell[1]))}", []).append(obj_id)
    return {k: v for k, v in sorted(cells.items()) if len(v) > 1}


SHOP_NOTE = ("a shop sells only to a unit of the buyer's standing close to it (measured: Tavern 300-350, Goblin "
             "Merchant 250) and not in the first seconds of a map; isto/usma 0 means never in stock")


def shop_report(project, catalog, ids: list[str] | None = None) -> dict:
    """Every entry of each shop's card - what it costs, its stock, hotkey and cell, and for a sold unit its race and
    requirement - with what stops a player buying it, so a whole card can be read in one call."""
    if ids is None:
        mods = [o["id"] for o in objdata_list(project, catalog, "unit")["objects"]]
        ids = [oid for oid in mods if any(objdata_get(project, catalog, "unit", oid, [f])["fields"].get(f, {}).get(
            "value") for f in ("usei", "useu"))]
        if not ids:
            return {"kind": "shop", "shops": [], "note": "no unit of this map sells anything (usei/useu); pass ids to "
                                                         "read a stock shop such as ngme or ntav"}
    shops = []
    for shop in ids:
        doc = objdata_get(project, catalog, "unit", shop, ["usei", "useu"])
        lists = {f: [x.strip() for x in str(doc["fields"].get(f, {}).get("value") or "").split(",") if x.strip()]
                 for f in ("usei", "useu")}
        entries, keys = [], {}
        for kind, field, cost, stock in (("item", "usei", ("igol", "ilum"), ("isto", "isit", "istr", "isst")),
                                         ("unit", "useu", ("ugol", "ulum"), ("usma", "usit", "usrg", "usst"))):
            extra = ("urac", "ureq") if kind == "unit" else ()
            for entry in lists[field]:
                wanted = [*cost, *stock, "uhot", "ubpx", "ubpy", *extra]
                try:
                    got = objdata_get(project, catalog, kind, entry, wanted)
                except ToolError:
                    entries.append({"id": entry, "kind": kind, "problems": [f"no {kind} {entry} exists"]})
                    continue
                f = {k: v.get("value", (v.get("values") or [None])[0]) for k, v in got["fields"].items()}
                row = {"id": entry, "kind": kind, "name": got.get("name"),
                       "gold": f.get(cost[0]), "lumber": f.get(cost[1]),
                       "stock": {k: f.get(k) for k in stock}, "hotkey": f.get("uhot"),
                       "cell": [f.get("ubpx"), f.get("ubpy")]}
                if kind == "unit":
                    row.update(race=f.get("urac"), requires=f.get("ureq") or None)
                problems = []
                if f.get(stock[0]) is not None and int(_number(f.get(stock[0]), 1)) == 0:
                    problems.append(f"{stock[0]} (Stock Maximum) 0: never in stock")
                if row["hotkey"]:
                    keys.setdefault(str(row["hotkey"]).upper(), []).append(entry)
                row["problems"] = problems
                entries.append(row)
        for key, sharing in keys.items():
            if len(sharing) > 1:
                for row in entries:
                    if row["id"] in sharing:
                        row["problems"].append(f"hotkey {key} shared with {', '.join(x for x in sharing if x != row['id'])}")
        shops.append({"id": shop, "name": doc.get("name"), "entries": entries,
                      "card": f"{len(entries)} of 12 cells" + (" - over the card, the rest never shows"
                                                               if len(entries) > 12 else "")})
    return {"kind": "shop", "shops": shops, "note": SHOP_NOTE}


def balance_report(project, catalog, kind: str = "unit", ids: list[str] | None = None, compare: bool = True) -> dict:
    """The map's own objects of one kind with their damage, staying power and cost, and the stock objects of the same
    price beside them. kind is unit, item or ability; ids defaults to what the map changed or created. kind="shop"
    lists every entry of each shop's card instead."""
    if kind == "shop":
        return shop_report(project, catalog, ids)
    if kind not in ("unit", "item", "ability"):
        raise ToolError("bad_kind", f"balance_report reads units, items, abilities and shops, not {kind!r}",
                        hint="objdata_list shows what the map holds")
    if ids is None:
        ids = [o["id"] for o in objdata_list(project, catalog, kind)["objects"]]
        if not ids:
            return {"kind": kind, "objects": [], "note": "this map has no custom or modified " + kind + "s "
                                                          "(objdata_edit creates one, or pass ids)"}
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ToolError("bad_value", "ids is a list of object ids", path="ids")
    misc = constants_ops.values(project, catalog) if kind == "unit" else {}
    cap = max(1, int(_number(misc.get("MaxHeroLevel"), 10)))
    stock, hero_stock = [], []
    if compare and kind == "unit":
        stock = _stock(project, catalog, kind, STOCK_UNITS, misc, cap)
    elif compare and kind == "item":
        stock = _stock(project, catalog, kind, STOCK_ITEMS)
    rows = []
    for obj_id in ids[:50]:
        fields, doc = _fields(project, catalog, kind, obj_id)
        if kind == "unit":
            row = {"id": obj_id, "name": doc.get("name", obj_id), "base": doc.get("base"),
                   **_unit(fields, misc, cap)}
            if "hero" in row and compare and not hero_stock:   # heroes belong beside heroes, not beside Peasants
                hero_stock = _stock(project, catalog, kind, STOCK_HEROES, misc, cap)
        elif kind == "item":
            row = {"id": obj_id, "name": doc.get("name", obj_id), "base": doc.get("base"),
                   **_item(fields, catalog, project)}
        else:
            row = {"id": obj_id, "name": doc.get("name", obj_id), "base": doc.get("base"),
                   **_ability(fields, int(doc.get("levels", 1)))}
        against = hero_stock if kind == "unit" and "hero" in row else stock
        if against:
            near = _closest(row, against, kind)
            row["closest_stock"] = [{k: v for k, v in s.items() if k in
                                     ("id", "name", "gold", "food", "damage_per_second", "effective_life", "mana",
                                      "damage_per_gold", "life_per_gold", "bonus_per_100_gold")} for s in near]
            flags = _flag(row, near, kind)
            if flags:
                row["flags"] = flags
        rows.append(row)
    out = {"kind": kind, "count": len(rows), "objects": rows}
    shared = button_cells(project, catalog, ids) if kind == "ability" else {}
    if shared:
        out["button_cells"] = shared
        out["button_note"] = ("these abilities sit on the same command-card cell (abpx, abpy); a unit that gets two of "
                              "them with UnitAddAbility shows only one. Button positions are object data, the same "
                              "for every player (BlzSetAbilityPosX/Y take an ability code, so they move it for "
                              "everyone): use one ability object per cell")
    if kind == "unit":
        out["formulas"] = {"damage_per_second": "(base + dice * (sides + 1) / 2) / cooldown, per enabled attack",
                           "effective_life": f"life / (1 - {ARMOUR_STEP} * armour / (1 + {ARMOUR_STEP} * armour))",
                           "worth": "sqrt(damage per second * effective life) per 100 gold and lumber"}
    if len(ids) > 50:
        out["note"] = f"{len(ids)} ids given; the first 50 are reported (pass ids to choose)"
    return out
