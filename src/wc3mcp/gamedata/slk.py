"""SYLK tables as shipped with Warcraft III (only C records carry data)."""
from dataclasses import dataclass


@dataclass
class Table:
    columns: list[str]
    rows: dict[str, dict[str, str]]


def _unquote(tok: str) -> str:
    return tok[1:-1] if len(tok) >= 2 and tok[0] == tok[-1] == '"' else tok


def parse_slk(data: bytes) -> Table:
    cells: dict[int, dict[int, str]] = {}
    x = y = 0
    for line in data.decode("utf-8", "replace").splitlines():
        if not line.startswith("C;"):
            continue
        parts = line.split(";")
        value = None
        for j in range(1, len(parts)):
            tag = parts[j][:1]
            if tag == "X":
                x = int(parts[j][1:])
            elif tag == "Y":
                y = int(parts[j][1:])
            elif tag == "K":  # value runs to the end of the line and may contain ';'
                value = _unquote(";".join(parts[j:])[1:])
                break
        if value is not None:
            cells.setdefault(y, {})[x] = value
    if not cells:
        return Table([], {})
    header = cells.pop(min(cells))
    width = max(header)
    columns = [header.get(i, "") for i in range(1, width + 1)]
    rows = {}
    for yy in sorted(cells):
        r = cells[yy]
        if 1 in r:
            rows[r[1]] = {columns[i - 1]: v for i, v in r.items() if 1 <= i <= width}
    return Table(columns, rows)
