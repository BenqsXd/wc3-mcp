"""Frame Definition Files (.fdf): the layout language of the game's own UI, and of custom UI a map loads with
BlzLoadTOCFile. Text in, text out; the parse keeps every statement in order, so a file survives a round trip even
when it uses a keyword this codec has never seen.

    Frame "BACKDROP" "MyPanel" INHERITS "QuestButtonBackdropTemplate" {
        Width 0.2,
        SetPoint TOPLEFT, "ConsoleUI", TOPLEFT, 0.01, -0.01,
    }
"""
import re

from .binary import FormatError

TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<line_comment>//[^\n]*)
  | (?P<block_comment>/\*.*?\*/)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<number>-?\d+(?:\.\d+)?)
  | (?P<punct>[{},])
  | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
""", re.X | re.S)
# blocks that hold statements of their own, like Frame does
BLOCK_WORDS = ("Frame", "String", "StringList", "Texture", "Layer")


def _tokens(text: str) -> list[tuple[str, str, bool]]:
    """(kind, text, whether a line ends after it). A comma at the end of a line closes a statement; commas inside a
    line only separate its arguments (SetPoint TOPLEFT, "Frame", TOPLEFT, 0.0, 0.0,)."""
    out, pos = [], 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if m is None:
            raise FormatError(f"cannot read the file at character {pos}: {text[pos:pos + 20]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind in ("space", "line_comment", "block_comment"):
            if out and "\n" in m.group():
                out[-1] = (out[-1][0], out[-1][1], True)
        else:
            out.append((kind, m.group(), False))
    return out


def _value(token):
    kind, text = token[0], token[1]
    if kind == "string":
        return text[1:-1]        # FDF strings are literal: a backslash is a path separator, not an escape
    if kind == "number":
        return float(text) if "." in text else int(text)
    return text


class _Parser:
    def __init__(self, text: str):
        self.tokens = _tokens(text)
        self.at = 0

    def peek(self, ahead: int = 0):
        return self.tokens[self.at + ahead] if self.at + ahead < len(self.tokens) else None

    def take(self):
        token = self.peek()
        if token is None:
            raise FormatError("the file ends in the middle of a statement")
        self.at += 1
        return token

    def statements(self, inside: bool) -> list[dict]:
        out = []
        while True:
            token = self.peek()
            if token is None or (inside and token[1] == "}"):
                if inside:
                    self.take()
                return out
            if token[1] == ",":      # a stray separator between statements
                self.take()
                continue
            out.append(self.statement())

    def statement(self) -> dict:
        kind, word = self.take()[:2]
        if kind != "word":
            raise FormatError(f"expected a keyword, found {word!r}")
        args = []
        while True:
            token = self.peek()
            if token is None or token[1] == "}":
                break
            if token[1] == ",":
                self.take()
                if token[2]:      # the comma ended the line, so it ended the statement
                    break
                continue
            if token[1] == "{":
                self.take()
                node = {"block": word, "args": args, "statements": self.statements(inside=True)}
                if self.peek() and self.peek()[1] == ",":
                    self.take()
                return node
            taken = self.take()
            args.append(_value(taken))
            if taken[2] and not (self.peek() and self.peek()[1] in (",", "{")):
                break             # a statement without a trailing comma, the next line starts a new one
        return {"key": word, "args": args}


def parse(data: bytes | str) -> list[dict]:
    """The file as a list of statements: {"key", "args"} for a plain line, {"block", "args", "statements"} for a
    Frame (or any other block). Order and unknown keywords are kept."""
    text = data.decode("utf-8-sig", "replace") if isinstance(data, bytes) else data
    return _Parser(text).statements(inside=False)


def _write_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)   # UI coordinates are fractions of the screen: keep every digit
    text = str(value)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text) and text.upper() == text:
        return text          # an enum value such as TOPLEFT or JUSTIFYRIGHT stays bare
    return '"' + text + '"'


def serialize(statements: list[dict], indent: int = 0) -> str:
    """The statements as FDF text, four spaces per level, a comma after every statement."""
    pad, out = "    " * indent, []
    for node in statements:
        if "block" in node:
            args = [_write_value(a) for a in node["args"]]
            if node["block"] == "Frame":   # the game wants Frame "TYPE" "Name" [INHERITS ["WITHCHILDREN"] "Template"]
                args = [a if a in ("INHERITS", "WITHCHILDREN") else '"' + str(v).strip('"') + '"'
                        for a, v in zip(args, node["args"])]
            head = " ".join([node["block"]] + args)
            out.append(f"{pad}{head} {{\n{serialize(node['statements'], indent + 1)}{pad}}}\n")
        else:
            args = " ".join(_write_value(a) for a in node["args"])
            out.append(f"{pad}{node['key']}{' ' + args if args else ''},\n")
    return "".join(out)


def frames(statements: list[dict], inherited: str | None = None):
    """Every Frame block in the file, depth first, as (type, name, statements, parent name)."""
    for node in statements:
        if node.get("block") == "Frame" and len(node["args"]) >= 2:
            frame_type, name = str(node["args"][0]), str(node["args"][1])
            yield frame_type, name, node, inherited
            yield from frames(node["statements"], name)
        elif "statements" in node:
            yield from frames(node["statements"], inherited)


def includes(statements: list[dict]) -> list[str]:
    return [str(node["args"][0]) for node in statements
            if node.get("key") == "IncludeFile" and node.get("args")]
