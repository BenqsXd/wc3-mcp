"""The script API of the installed game: natives, Blizzard.j functions, constants and types, parsed from the
declarations in Scripts/common.j, Scripts/Blizzard.j and Scripts/common.ai. Reading a signature here stops a script
from guessing one, and the answer is this install's build, not a remembered patch."""
import re
from dataclasses import dataclass

SOURCES = ("Scripts/common.j", "Scripts/Blizzard.j", "Scripts/common.ai")
DECL = re.compile(r"(?m)^\s*(?:(constant)\s+)?(native|function)\s+(\w+)\s+takes\s+(.*?)\s+returns\s+(\w+)")
TYPE = re.compile(r"(?m)^\s*type\s+(\w+)\s+extends\s+(\w+)")
GLOBAL = re.compile(r"(?m)^\s*constant\s+(\w+)\s+(\w+)\s*=\s*(.+?)\s*$")


@dataclass(frozen=True)
class Entry:
    id: str
    what: str            # native | function | constant | type
    file: str
    params: tuple[tuple[str, str], ...] = ()   # (type, name)
    returns: str = ""
    value: str = ""      # constants: the literal or expression the declaration assigns
    base: str = ""       # types: the type it extends

    @property
    def signature(self) -> str:
        if self.what == "type":
            return f"type {self.id} extends {self.base}"
        if self.what == "constant":
            return f"constant {self.returns} {self.id} = {self.value}"
        args = ", ".join(f"{t} {n}" for t, n in self.params) or "nothing"
        return f"{self.what} {self.id} takes {args} returns {self.returns}"

    def to_json(self) -> dict:
        doc = {"id": self.id, "what": self.what, "file": self.file, "signature": self.signature}
        if self.what in ("native", "function"):
            doc["params"] = [{"type": t, "name": n} for t, n in self.params]
            doc["returns"] = self.returns
        elif self.what == "constant":
            doc.update(type=self.returns, value=self.value)
        else:
            doc["base"] = self.base
        if self.id in NOTES:
            doc["observed"] = NOTES[self.id]
        return doc


# What map sessions measured these natives doing in the game, where that differs from what the name promises. Each was
# seen in a game run (see the skill's references/game-behaviour.md); data_search and data_get kind=native carry them.
NOTES = {
    "SetUnitAcquireRange": "0 is ignored (the unit keeps its type's range); 1 reads back as 200, and a unit that is "
                           "attacked still retaliates. PauseUnit is what holds a creep passive until it is hit",
    "BlzSetUnitWeaponBooleanField": "UNIT_WEAPON_BF_ATTACKS_ENABLED false did not stop a creep attacking; PauseUnit "
                                    "did",
    "PauseUnit": "a paused unit holds its ground, still takes damage and can be attacked and right-clicked; it keeps "
                 "its order id, so GetUnitCurrentOrder says nothing about whether it acts. Scripted damage from a "
                 "paused hero still goes out",
    "IssueNeutralImmediateOrderById": "returned false for every hero of a Tavern that listed them, with distance, "
                                      "gold, food and stock ruled out, while IssueImmediateOrderById(shop, id) sold "
                                      "one: its false is no proof that a player cannot buy",
    "ForceUIKey": "presses a key on a unit's own command card (it opens the learn menu); it did nothing on a neutral "
                  "shop's card, so it is no click emulator for a shop",
    "UnitRemoveAbility": "does nothing to an unlearned hero ability (it stays in the learn menu); a uhab ability "
                         "removed and added back arrives learned at rank 1 with no point spent",
    "BlzUnitHideAbility": "hides command-card buttons only, never a learn-menu button",
    "GetUnitName": "for a hero this is the unit type's name; the hero's own name is GetHeroProperName (upro, upru)",
    "BlzGetUnitBaseDamage": "on a hero it already includes the primary attribute: add dice and item bonuses, not the "
                            "attribute again",
    "SetUnitPosition": "puts the unit on the nearest walkable spot, which can be past a clamp (a 600 blink once landed "
                       "676 away); SetUnitX/Y would leave it inside a cliff",
    "DialogDisplay": "a shown dialog pauses a single-player game - no timers, no TriggerSleepAction, no probe - until "
                     "it is clicked: open it on a short timer, not at map init (game_test probe_init with "
                     "ProbeSkipDialogs gets a probe past one)",
    "SetUnitInvulnerable": "takes the unit out of target acquisition entirely, and a Fountain of Health no longer heals "
                           "it; its owner can still walk it and buy from a shop with it",
    "SetUnitState": "UNIT_STATE_MAX_LIFE does not change max life; BlzSetUnitMaxHP does",
    "BlzSetUnitMaxHP": "changes max life (SetUnitState with UNIT_STATE_MAX_LIFE does not)",
    "GroupEnumUnitsInRange": "returns corpses too, and they still answer GetUnitTypeId, BlzGetUnitMaxHP and their "
                             "owner: test GetUnitState(u, UNIT_STATE_LIFE) > 0.405 (lint: corpse_enum)",
    "TriggerAddAction": "a damage handler added this way runs on a new thread after the damage call returned, when "
                        "globals the dealer set around UnitDamageTarget are reset; TriggerAddCondition runs it inside "
                        "the call (lint: damage_action)",
    "RemoveItem": "fires EVENT_PLAYER_UNIT_DROP_ITEM while the item still counts as carried, so an item-event handler "
                  "that changes the inventory re-enters itself (lint: item_reentry)",
    "UnitAddItemById": "fires EVENT_PLAYER_UNIT_PICKUP_ITEM, re-entering your own item handler; an item handed over in "
                       "the same instant as ReviveHero does not arrive - give it a tick later",
    "MultiboardDisplay": "a multiboard created and displayed during map initialization never appears; build it on the "
                         "first timer tick",
    "BlzLoadTOCFile": "the .toc lists files by archive path (war3mapImported\\X.fdf) and ends with blank lines; a bare "
                      "file name loads nothing and every BlzCreateFrame of its templates returns null",
    "BlzFrameClick": "fires FRAMEEVENT_CONTROL_CLICK: how a probe presses a frame button (hover cannot be faked)",
    "OrderId": "returns 0 for a string the game's order table lacks (holywrath, lightsmercy, surgeoflight); "
               "data_search kind=order says which strings resolve",
    "TimerGetElapsed": "one free timer (TimerStart(t, 1000000, false, null)) read with this is a clock that does not "
                       "drift; a countdown that subtracts a fixed step per tick does",
    "IssuePointOrder": "a move to a point beside a waygate stops about 110 short and nothing happens; "
                       "IssueTargetOrder(u, \"smart\", gate) uses the gate",
    "BlzSetAbilityResearchTooltip": "set per ability code, so the same for every player; inside a GetLocalPlayer block "
                                    "each player sees their own text without a desync (tooltips are only drawn)",
}


def _params(text: str) -> tuple[tuple[str, str], ...]:
    if text.strip() == "nothing":
        return ()
    out = []
    for pair in text.split(","):
        words = pair.split()
        if len(words) >= 2:
            out.append((" ".join(words[:-1]), words[-1]))
    return tuple(out)


def parse(sources: dict[str, str]) -> dict[str, Entry]:
    """{name: Entry} over the given {file: text}; an earlier file wins (common.j before Blizzard.j)."""
    out: dict[str, Entry] = {}
    for name, text in sources.items():
        for m in TYPE.finditer(text):
            out.setdefault(m[1], Entry(m[1], "type", name, base=m[2]))
        for m in DECL.finditer(text):
            out.setdefault(m[3], Entry(m[3], m[2], name, params=_params(m[4]), returns=m[5]))
        for m in GLOBAL.finditer(text):
            if m[3].startswith("function "):   # constant boolexpr-style aliases are not values
                continue
            out.setdefault(m[2], Entry(m[2], "constant", name, returns=m[1], value=m[3]))
    return out


def search(entries: dict[str, Entry], query: str) -> list[dict]:
    """Entries whose name, signature or type matches `query` (a substring, or a glob with * or ?)."""
    q = query.casefold()
    glob = any(c in query for c in "*?")
    if glob:
        pattern = re.compile(re.escape(q).replace(r"\*", ".*").replace(r"\?", "."))
    rows = []
    for e in entries.values():
        text = e.signature.casefold()
        if (pattern.fullmatch(e.id.casefold()) if glob else (q in e.id.casefold() or q in text)):
            rows.append({"id": e.id, "what": e.what, "signature": e.signature,
                         **({"observed": NOTES[e.id]} if e.id in NOTES else {})})
    rows.sort(key=lambda r: (r["what"] != "native", r["id"]))
    return rows
