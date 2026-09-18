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
        return doc


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
            rows.append({"id": e.id, "what": e.what, "signature": e.signature})
    rows.sort(key=lambda r: (r["what"] != "native", r["id"]))
    return rows
