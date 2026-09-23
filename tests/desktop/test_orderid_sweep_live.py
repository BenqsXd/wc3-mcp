"""One game run that asks the game's own OrderId() about every order string the data and the editor know
(pytest -m game), and writes the answers to src/wc3mcp/gamedata/orderids.json, which data_search kind=order
(resolves, order_id) and map_validate channel_order read. OrderId returning 0 means the game has no such order: a
Channel copy with that base order can never be cast."""
import json
import shutil
from datetime import date

import pytest

from corpus import _storage, ladder_maps
from wc3mcp.desktop import game
from wc3mcp.gamedata import orderids
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops import probe


def _orders() -> list[str]:
    """Every order string of the base data and of the balance layer maps use, lower case and deduplicated."""
    found: dict[str, str] = {}
    for balance in (None, "Custom_V1"):
        for row in Catalog(_storage(), balance=balance)._orders.values():
            found.setdefault(row["id"].casefold(), row["id"])
    return sorted(found.values(), key=str.casefold)


def sweep_script(orders: list[str]) -> str:
    return "\n".join(f'call ProbeReport("{o}=" + I2S(OrderId("{o}")))' for o in orders)


@pytest.mark.game
def test_every_order_string_against_the_games_own_order_id(tmp_path):
    orders = _orders()
    jass = ladder_maps()[0]
    target = tmp_path / "Orders.w3x"
    shutil.copyfile(jass, target)
    catalog = Catalog(_storage(), balance="Custom_V1")
    copy = probe.build(target, tmp_path / "probe" / target.name, catalog, seconds=3, user=sweep_script(orders))
    result = game.Game().test(copy, results=[probe.REPORT], timeout=240)
    assert result["missing"] == [], result
    report = probe.parse(result["results"][probe.REPORT])
    ids = {}
    for line in report["reports"]:
        order, _, number = line.partition("=")
        ids[order] = int(number)
    assert set(ids) == set(orders), sorted(set(orders) - set(ids))[:10]
    assert ids["thunderbolt"] != 0 and all(ids[o] == 0 for o in orderids.FAIL)   # what map sessions found by hand
    orderids.SWEEP_FILE.write_text(json.dumps({"measured": date.today().isoformat(), "strings": len(ids),
                                               "unknown_to_the_game": sorted(o for o, n in ids.items() if n == 0),
                                               "ids": dict(sorted(ids.items()))}, indent=1), encoding="utf-8")
    orderids.sweep.cache_clear()
