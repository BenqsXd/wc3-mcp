"""war3map.wts — trigger strings. Parsed losslessly: everything outside the string bodies is kept verbatim."""
import re
from dataclasses import dataclass, field

_HEADER = re.compile(r"^(?:﻿|ï»¿)?STRING\s+(-?\d+)\s*$")  # plain or double-encoded BOM
TRIGSTR = re.compile(r"^TRIGSTR_(-?\d+)$")


@dataclass
class Entry:
    id: int
    lead: str            # text before the STRING line (blank lines, BOM, stray lines)
    header: str          # the STRING line including its line ending
    comments: list[str]  # lines between the STRING line and "{"
    opening: str         # the "{" line
    body: str            # raw lines between the braces, including their line endings
    closing: str         # the "}" line ("" if the file ended early)


def _text(body: str) -> str:
    for nl in ("\r\n", "\n", "\r"):
        if body.endswith(nl):
            body = body[:-len(nl)]
            break
    return body.replace("\r\n", "\n")


@dataclass
class TriggerStrings:
    entries: list[Entry] = field(default_factory=list)
    tail: str = ""
    newline: str = "\r\n"

    @classmethod
    def parse(cls, data: bytes) -> "TriggerStrings":
        text = data.decode("utf-8", "surrogateescape")
        lines = text.splitlines(keepends=True)
        ts = cls(newline="\n" if "\n" in text and "\r\n" not in text else "\r\n")
        lead, i = "", 0
        while i < len(lines):
            m = _HEADER.match(lines[i].rstrip("\r\n"))
            if not m:
                lead += lines[i]
                i += 1
                continue
            j = i + 1
            while j < len(lines) and not lines[j].rstrip("\r\n").startswith("{"):
                j += 1
            if j >= len(lines):  # no opening brace: keep the rest verbatim
                lead += "".join(lines[i:])
                break
            k = j + 1
            while k < len(lines) and lines[k].rstrip("\r\n") != "}":
                k += 1
            ts.entries.append(Entry(int(m.group(1)), lead, lines[i], lines[i + 1:j], lines[j],
                                    "".join(lines[j + 1:k]), lines[k] if k < len(lines) else ""))
            lead, i = "", k + 1
        ts.tail = lead
        return ts

    def serialize(self) -> bytes:
        text = "".join(e.lead + e.header + "".join(e.comments) + e.opening + e.body + e.closing
                       for e in self.entries) + self.tail
        return text.encode("utf-8", "surrogateescape")

    def get(self, sid: int) -> str | None:
        return next((_text(e.body) for e in self.entries if e.id == sid), None)

    def _body(self, text: str) -> str:
        return text.replace("\r\n", "\n").replace("\n", self.newline) + self.newline if text else ""

    def set(self, sid: int, text: str) -> None:
        hits = [e for e in self.entries if e.id == sid]
        if not hits:
            self.add(text, sid)
        for e in hits:  # duplicate ids occur in real files; keep them consistent
            e.body = self._body(text)

    def add(self, text: str, sid: int | None = None) -> int:
        if sid is None:
            sid = max((e.id for e in self.entries), default=0) + 1
        nl = self.newline
        if self.entries:
            lead = nl
        else:
            lead, self.tail = (self.tail or "﻿"), ""
        self.entries.append(Entry(sid, lead, f"STRING {sid}{nl}", [], "{" + nl, self._body(text), "}" + nl))
        return sid

    def remove(self, sid: int) -> int:
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.id != sid]
        return before - len(self.entries)

    def resolve(self, value: str) -> str:
        m = TRIGSTR.match(value)
        if not m:
            return value
        text = self.get(int(m.group(1)))
        return value if text is None else text
