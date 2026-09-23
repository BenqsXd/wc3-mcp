"""What the game's own OrderId() answers for an order string. The editor's presets and the ability data name 345 order
strings, and not every one of them is in the game's order table: holywrath, lightsmercy and surgeoflight make OrderId
return 0, and a Channel copy whose base order is one of them can never be cast - with nothing static to say so.
The sweep of 2026-09-23 found 32 of 347 strings unknown to the game, 15 of them used by shipped abilities (bash,
manashield, slimemonster, phoenix, ...): a backing ability is no proof. It asked with the spelling the data uses.

orderids.json beside this file, when present, holds a full in-game sweep (tests/desktop/test_orderid_sweep_live.py
writes it): order string -> the id OrderId returned, 0 for an unknown string. Without it only the strings map sessions
checked by hand are known either way."""
import json
from functools import cache
from pathlib import Path

SWEEP_FILE = Path(__file__).with_name("orderids.json")
# OrderId returned 0 in the game (MapB phase 6, 2026-09-22): a Channel on one of these is inert
FAIL = frozenset({"holywrath", "lightsmercy", "surgeoflight"})
# no shipped ability uses these, and they resolved and cast in game runs (MapB phase 6; MapC)
RESOLVE = frozenset({"witheringfire", "valiantcharge", "consecration", "warcry", "breathoffrost", "firebolt", "drain",
                     "inspirecourage", "avengerform", "lavamonster", "summonphoenix", "dreadlordinferno"})


@cache
def sweep() -> dict[str, int]:
    """order string (lower case) -> OrderId in the game, from the last full sweep; empty when none has run."""
    try:
        data = json.loads(SWEEP_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return {k.casefold(): int(v) for k, v in data.get("ids", {}).items()}


def resolves(order: str) -> bool | None:
    """True when the game is known to resolve the string, False when OrderId is known to return 0 for it, None when
    nobody has checked (a string a shipped ability uses is very likely fine, but likely is not measured)."""
    key = order.casefold()
    measured = sweep()
    if key in measured:
        return measured[key] != 0
    if key in FAIL:
        return False
    return True if key in RESOLVE else None


def order_id(order: str) -> int | None:
    """The id OrderId returns for the string, when the sweep has measured it."""
    return sweep().get(order.casefold())
