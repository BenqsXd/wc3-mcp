"""Desync reports the game writes after a network desync: the checksum log (Logs\\<...>_Desync.log, also copied to
Errors\\<date>\\) and the crash-report summary (Errors\\<date>\\Desync.txt).

The log holds, for the desync turn and the two before it, one block per checksummed subsystem:
    [Desync - 1768977253 - Turn(00012529) = 108275616]
        #0#: 0x00078357
The block id is a FourCC read as a big-endian int (1768977253 = 'ipse'); so are most keys inside it, often a base id
plus a field index ('tech' + 1 = 'teci'). Keys nest by tab depth. A section may occur more than once per turn
('cust' six times), so sections are told apart by (id, occurrence). Comparing the logs of the players of one game
shows which subsystem went apart first, and the first value inside it that differs."""
import re
from dataclasses import dataclass, field

HEAD = re.compile(r"\[Desync - (\d+) - Turn\((\d+)\) = (\d+)\]")
LINE = re.compile(r"^(\t*)#(-?\d+)#(?::\s*(0x[0-9A-Fa-f]+))?\s*$")
SUMMARY = re.compile(r"Network desync on turn (\d+) in game (\S+)")
CHECKSUM = re.compile(r"^War3 (.+?) checksum ([0-9a-fA-F]+)\s*$")
FIELD = re.compile(r"^<(Map|PlayerCount|GameType|Race|Exception\.BuildNumber|MapHash)>\s*(.*?)\s*$")


def name(number: int) -> str:
    """A FourCC id as text ('ipse'), or the number when its bytes are not printable."""
    raw = (number & 0xFFFFFFFF).to_bytes(4, "big")
    return raw.decode("ascii") if number > 0xFFFFFF and all(0x20 < b < 0x7F for b in raw) else str(number)


def value(hex_text: str) -> str:
    text = name(int(hex_text, 16))
    return hex_text if text.isdigit() else f"{hex_text} ({text})"


@dataclass
class Section:
    id: str
    occurrence: int              # 0 for the first block of this id in this turn
    turn: int
    checksum: int
    lines: list[tuple[str, str | None]] = field(default_factory=list)   # (key path, value or None for a group)


@dataclass
class DesyncFile:
    kind: str                    # "log" | "report"
    sections: list[Section] = field(default_factory=list)
    info: dict = field(default_factory=dict)


def parse_log(text: str) -> DesyncFile:
    out = DesyncFile("log")
    seen: dict[tuple[str, int], int] = {}
    current, path = None, []
    for raw in text.splitlines():
        head = HEAD.match(raw)
        if head:
            sid, turn = name(int(head[1])), int(head[2])
            n = seen[(sid, turn)] = seen.get((sid, turn), -1) + 1
            current, path = Section(sid, n, turn, int(head[3])), []
            out.sections.append(current)
            continue
        line = LINE.match(raw)
        if current is None or not line:
            continue
        depth, key = len(line[1]), name(int(line[2]))
        del path[max(depth - 1, 0):]
        path.append(key)
        current.lines.append(("/".join(path), value(line[3]) if line[3] else None))
    return out


def parse_report(text: str) -> DesyncFile:
    out = DesyncFile("report")
    summary = SUMMARY.search(text)
    turn = int(summary[1]) if summary else 0
    if summary:
        out.info.update(turn=turn, game=summary[2])
    for raw in text.splitlines():
        m = CHECKSUM.match(raw)
        if m:
            out.sections.append(Section(m[1], 0, turn, int(m[2], 16)))
        f = FIELD.match(raw)
        if f and f[1] not in out.info:
            out.info[f[1]] = f[2]
    return out


def parse(text: str) -> DesyncFile:
    return parse_log(text) if HEAD.search(text) else parse_report(text)


def first_difference(sections: list[Section]) -> dict | None:
    """The first line whose key or value is not the same in every one of these sections (one per file)."""
    for i in range(max(len(s.lines) for s in sections)):
        rows = [s.lines[i] if i < len(s.lines) else None for s in sections]
        if any(r != rows[0] for r in rows):
            return {"line": i, "values": [None if r is None else {"key": r[0], "value": r[1]} for r in rows]}
    return None


def compare(files: list[DesyncFile]) -> list[dict]:
    """Sections whose checksum is not the same in every file, in the first file's order; a section missing from a
    file counts as a difference."""
    index = [{(s.id, s.occurrence, s.turn): s for s in f.sections} for f in files]
    out = []
    for s in files[0].sections:
        key = (s.id, s.occurrence, s.turn)
        found = [ix.get(key) for ix in index]
        sums = [None if x is None else x.checksum for x in found]
        if all(v == sums[0] for v in sums):
            continue
        row = {"section": s.id, "occurrence": s.occurrence, "turn": s.turn,
               "checksums": [None if v is None else f"{v:08x}" for v in sums]}
        present = [x for x in found if x is not None]
        if len(present) == len(found) and any(x.lines for x in present):
            row["first_difference"] = first_difference(present)
        out.append(row)
    return out
