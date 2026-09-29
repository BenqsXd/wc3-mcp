"""replay_read and desync_read: an online playtest's replay (.w3g) and desync reports, read without the game."""
from collections import Counter
from pathlib import Path

from .. import config
from ..errors import ToolError
from ..formats import desync, w3g
from ..formats.binary import FormatError
from ..gamedata import orderids

ORDER_KINDS = ("order", "order_point", "order_target", "give_item", "order_two_points", "command")
MAX_LIMIT = 2000


def _file(path: str, arg: str) -> Path:
    """A local file; a relative path is also looked up under Documents\\Warcraft III (Logs\\..., Errors\\...)."""
    p = Path(path)
    if not p.is_file() and not p.is_absolute() and (config.documents() / p).is_file():
        p = config.documents() / p
    if not p.is_file():
        raise ToolError("not_found", f"{arg}: no such file {path}",
                        hint="replays: Documents\\Warcraft III\\BattleNet\\<id>\\Replays and Logs; wc3_help('replays')",
                        path=arg)
    return p


def _time(ms: int) -> str:
    return f"{ms // 60000}:{ms % 60000 / 1000:04.1f}"


def _timed(row: dict) -> dict:
    return {"time": _time(row["time_ms"]), "player": row["player_id"],
            **{k: v for k, v in row.items() if k not in ("time_ms", "player_id")}}


def _order_names() -> dict[int, str]:
    names = {}
    for order, oid in sorted(orderids.sweep().items()):
        if oid:
            names.setdefault(oid, order)
    return names


def replay_read(path: str, player=None, kinds: list[str] | None = None, limit: int = 100, offset: int = 0) -> dict:
    source = _file(path, "path")
    try:
        rp = w3g.parse(source.read_bytes(), _order_names())
    except FormatError as e:
        hint = "TempReplay.w3g is the replay of a game still running; the game writes its header at the end" \
            if source.name.lower() == "tempreplay.w3g" else None
        raise ToolError("bad_format", f"{source}: {e}", hint=hint, path="path") from e
    slots = {s["player_id"]: s for s in rp.slots}
    counts: dict[int, Counter] = {}
    for a in rp.actions:
        counts.setdefault(a["player_id"], Counter())[a["action"]] += 1
    players = []
    for pid, pname in sorted(rp.players.items()):
        slot = slots.get(pid)
        players.append({"id": pid, "name": pname, "host": pid == rp.game.get("host_id"),
                        **({k: slot[k] for k in ("team", "color", "race", "computer")} if slot else {"slot": None}),
                        "actions": sum(counts.get(pid, {}).values()),
                        "action_counts": dict(counts.get(pid, Counter()).most_common())})
    wanted = None
    if player is not None:
        match = [p["id"] for p in players if str(player) == str(p["id"]) or str(player).casefold() in p["name"].casefold()]
        if not match:
            raise ToolError("bad_value", f"player {player!r} is not in this replay",
                            hint="players: " + ", ".join(f"{p['id']} {p['name']}" for p in players), path="player")
        wanted = set(match)
    known = {name for name, _ in w3g.ACTIONS.values()}
    kinds = list(kinds or ORDER_KINDS)
    bad = [k for k in kinds if k not in known]
    if bad:
        raise ToolError("bad_value", f"unknown action kinds {bad}", hint="kinds: " + ", ".join(sorted(known)),
                        path="kinds")
    rows = [a for a in rp.actions if a["action"] in kinds and (wanted is None or a["player_id"] in wanted)]
    limit, offset = max(0, min(limit, MAX_LIMIT)), max(offset, 0)
    shown = [_timed(a) for a in rows[offset:offset + limit]]
    chat = [_timed(c) for c in rp.chat if wanted is None or c["player_id"] in wanted]
    return {"path": str(source), "header": {**rp.header, "length": _time(rp.header["length_ms"])},
            "game": rp.game, "players": players,
            "chat": chat[:MAX_LIMIT], "leaves": [_timed(x) for x in rp.leaves],
            "parsed": {**rp.end, "reached_end": rp.end.get("reason") in ("end of data", "padding"),
                       "unknown_actions": rp.unknown},
            "kinds": kinds, "total": len(rows), "offset": offset, "returned": len(shown), "actions": shown}


def _sections(f: desync.DesyncFile) -> list[dict]:
    rows: dict[tuple, dict] = {}
    for s in f.sections:
        row = rows.setdefault((s.id, s.occurrence), {"section": s.id, "occurrence": s.occurrence, "checksums": {},
                                                     "lines": len(s.lines)})
        row["checksums"][str(s.turn)] = f"{s.checksum:08x}"
    return list(rows.values())


def desync_read(paths: list[str], limit: int = 20) -> dict:
    if not paths:
        raise ToolError("bad_value", "give at least one desync file", path="paths")
    files, parsed = [], []
    for i, path in enumerate(paths):
        source = _file(path, f"paths[{i}]")
        f = desync.parse(source.read_text("utf-8", "replace"))
        if not f.sections:
            raise ToolError("bad_format", f"{source}: no desync checksums found", path=f"paths[{i}]",
                            hint="Logs\\<...>_Desync.log or Errors\\<date>\\Desync.txt")
        parsed.append(f)
        files.append({"path": str(source), "kind": f.kind, **({"info": f.info} if f.info else {}),
                      "turns": sorted({s.turn for s in f.sections}), "sections": _sections(f)})
    out: dict = {"files": files}
    for kind in ("log", "report"):
        group = [(i, f) for i, f in enumerate(parsed) if f.kind == kind]
        if len(group) > 1:
            diffs = desync.compare([f for _, f in group])
            out.setdefault("differences", []).append({"kind": kind, "files": [i for i, _ in group], "count": len(diffs),
                                                      "sections": diffs[:max(limit, 0)]})
    if "differences" not in out:
        out["note"] = "one file per kind: pass the same game's logs from two or more players to compare them"
    return out
