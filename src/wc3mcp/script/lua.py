"""Editor-generated JASS -> the World Editor's war3map.lua. The editor writes Lua maps by building its JASS script and
transpiling it line by line; transpile() does the same, byte-identical on all 94 local Lua corpus maps and on Lua
maps saved by the current editor. Lines starting with RAW are Lua already (the map header, custom text triggers and
GUI Custom Script actions) and pass through unchanged."""
import re
from functools import lru_cache

RAW = "\x01"   # build.new_script(raw=RAW) marks the map's own Lua lines with this

_TOKEN = re.compile(r"""\s*(?:(?P<str>"(?:[^"\\]|\\.)*")|(?P<raw>'[^']*')|(?P<num>\$[0-9A-Fa-f]+|0[xX][0-9A-Fa-f]+|\d+\.\d*|\.\d+|\d+)|"""
                    r"""(?P<id>[A-Za-z_]\w*)|(?P<op>==|!=|<=|>=|[-+*/<>=(),\[\]]))""")
_SIGNATURE = re.compile(r"^\s*(?:constant\s+)?(?:native|function)\s+(\w+)\s+takes\s+(.*?)\s+returns\s+(\w+)", re.M)
_GLOBAL = re.compile(r"^\s*(?:constant\s+)?(\w+)(\s+array)?\s+(\w+)\s*(?:=\s*(.*))?$")
_FUNCTION = re.compile(r"^function (\w+) takes (.*?) returns (\w+)$")
_LOCAL = re.compile(r"^local (\w+)(\s+array)?\s+(\w+)(?:\s*=\s*(.*))?$")
_SET = re.compile(r"^set (\w+)(?:\[(.*)\])?\s*=\s*(.*)$")
_MAIN = re.compile(r"^function main\(\)\r?\n( *)\S", re.M)
_LOCALS = re.compile(r"^function (?!Trig_|InitTrig_)\w+\(\)\r?\n(?:[ ]*local [^\r\n]*\r?\n)+([ ]*\r?\n)?", re.M)
DEFAULTS = {"integer": "0", "real": "0.0", "boolean": "false", "string": '""'}
COMPARE = {"==", "!=", "<", "<=", ">", ">="}
_LEVELS = (("or",), ("and",), tuple(COMPARE), ("+", "-"), ("*", "/"))


class Types:
    """Function signatures (parameter types, return type) and global variable types of JASS sources."""

    def __init__(self, *sources: str):
        self.functions: dict[str, tuple[list[str], str]] = {}
        self.globals: dict[str, str] = {}
        for text in sources:
            self.add(text)

    def add(self, text: str) -> None:
        for m in _SIGNATURE.finditer(text):
            params = [] if m.group(2).strip() == "nothing" else [p.split()[0] for p in m.group(2).split(",")]
            self.functions[m.group(1)] = (params, m.group(3))
        inside = False
        for line in text.splitlines():
            s = line.strip()
            if s in ("globals", "endglobals"):
                inside = s == "globals"
            elif inside and s and not s.startswith("//"):
                m = _GLOBAL.match(s)
                if m:
                    self.globals[m.group(3)] = m.group(1)

    def copy(self) -> "Types":
        out = Types()
        out.functions, out.globals = dict(self.functions), dict(self.globals)
        return out


@lru_cache(maxsize=4)
def natives(catalog) -> Types:
    """common.j and Blizzard.j of the catalog's game build."""
    return Types(*((catalog._read(f"Scripts/{name}") or b"").decode("utf-8", "replace") for name in ("common.j", "Blizzard.j")))


def style(lua: str) -> tuple[bool, bool]:
    """(indented, blank line after locals) of an editor-written war3map.lua; the current editor's style when unknown."""
    main = _MAIN.search(lua)
    blanks = [bool(m.group(1)) for m in _LOCALS.finditer(lua)]
    return bool(main and main.group(1)), blanks[0] if blanks else True


def editor_generated(lua: str) -> bool:
    return bool(re.search(r"^function main\(\)\r?$", lua, re.M) and re.search(r"^function config\(\)\r?$", lua, re.M))


# ---- expressions -----------------------------------------------------------------------------------------------
def _tokens(text: str) -> list[tuple[str, str]]:
    out, pos, text = [], 0, text.rstrip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise ValueError(f"cannot read JASS at {text[pos:pos + 20]!r}")
        out.append((m.lastgroup, m.group(m.lastgroup)))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, text: str):
        self.t, self.i = _tokens(text), 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, value=None):
        tok = self.peek()
        if tok[0] is None or value is not None and tok[1] != value:
            raise ValueError(f"expected {value or 'more'!r} in JASS expression, got {tok[1]!r}")
        self.i += 1
        return tok

    def binary(self, level: int = 0):
        if level == len(_LEVELS):
            return self.unary()
        left = self.binary(level + 1)
        while self.peek()[1] in _LEVELS[level]:
            left = ("bin", self.take()[1], left, self.binary(level + 1))
        return left

    def unary(self):
        value = self.peek()[1]
        if value in ("not", "-"):
            self.take()
            return ("not" if value == "not" else "neg", self.unary())
        return self.primary()

    def primary(self):
        kind, value = self.take()
        if kind in ("str", "raw", "num"):
            return (kind, value)
        if value == "(":
            inner = self.binary()
            self.take(")")
            return ("paren", inner)
        if value == "function":
            return ("code", self.take()[1])
        if kind != "id":
            raise ValueError(f"unexpected {value!r} in JASS expression")
        if self.peek()[1] == "(":
            self.take("(")
            args = []
            if self.peek()[1] != ")":
                args.append(self.binary())
                while self.peek()[1] == ",":
                    self.take(",")
                    args.append(self.binary())
            self.take(")")
            return ("call", value, args)
        if self.peek()[1] == "[":
            self.take("[")
            index = self.binary()
            self.take("]")
            return ("index", value, index)
        return ("id", value)


def _parse(text: str):
    p = _Parser(text)
    node = p.binary()
    if p.i != len(p.t):
        raise ValueError(f"unexpected {p.peek()[1]!r} in JASS expression {text!r}")
    return node


class _Printer:
    def __init__(self, types: Types, local_types: dict):
        self.types, self.locals = types, local_types

    def var_type(self, name: str) -> str | None:
        return self.locals.get(name) or self.types.globals.get(name)

    def type_of(self, n) -> str | None:
        kind = n[0]
        if kind in ("str", "raw", "num"):
            return {"str": "string", "raw": "integer"}.get(kind) or ("real" if "." in n[1] else "integer")
        if kind == "id":
            return "boolean" if n[1] in ("true", "false") else "null" if n[1] == "null" else self.var_type(n[1])
        if kind == "call":
            return self.types.functions.get(n[1], ([], None))[1]
        if kind == "index":
            return self.var_type(n[1])
        if kind in ("paren", "neg"):
            return self.type_of(n[1])
        if kind == "not" or kind == "bin" and n[1] in COMPARE | {"and", "or"}:
            return "boolean"
        if kind == "bin":
            lt, rt = self.type_of(n[2]), self.type_of(n[3])
            if n[1] == "+" and "string" in (lt, rt):
                return "string"
            return "real" if "real" in (lt, rt) else lt or rt
        return None

    def show(self, n, expect: str | None = None) -> str:
        kind = n[0]
        if kind == "str":
            return n[1]
        if kind == "raw":
            return f'FourCC("{n[1][1:-1]}")'
        if kind == "num":
            return "0x" + n[1][1:] if n[1].startswith("$") else n[1]
        if kind == "id":
            return ('""' if expect == "string" else "nil") if n[1] == "null" else n[1]
        if kind == "code":
            return n[1]
        if kind == "call":
            params = self.types.functions.get(n[1], ([], None))[0]
            return f"{n[1]}({', '.join(self.show(a, params[i] if i < len(params) else None) for i, a in enumerate(n[2]))})"
        if kind == "index":
            return f"{n[1]}[{self.show(n[2])}]"
        if kind == "paren":
            return f"({self.show(n[1], expect)})"
        if kind == "not":
            return f"not {self.show(n[1])}"
        if kind == "neg":
            return f"-{self.show(n[1])}"
        op, lt, rt = n[1], self.type_of(n[2]), self.type_of(n[3])
        if op == "+" and "string" in (lt, rt):
            op = ".."
        elif op == "!=":
            op = "~="
        elif op == "/" and lt == rt == "integer":
            op = "//"
        # the editor types null by the other side for == < > only: `s != null` stays `s ~= nil` for strings too
        side = "string" if op == ".." else (lt if lt not in (None, "null") else rt) if op in COMPARE else None
        return f"{self.show(n[2], side)} {op} {self.show(n[3], side)}"

    def value(self, text: str, jass_type: str | None) -> str:
        shown = self.show(_parse(text), jass_type)
        return shown + ".0" if jass_type == "real" and re.fullmatch(r"-?\d+", shown) else shown


def _condition(printer: _Printer, text: str) -> str:
    node = _parse(text)
    while node[0] == "paren":
        node = node[1]
    return printer.show(node)


# ---- statements ------------------------------------------------------------------------------------------------
def transpile(jass: str, natives: Types, indented: bool = False, blank_after_locals: bool = True) -> str:
    """war3map.lua (CRLF) for an editor-generated war3map.j."""
    types = natives.copy()
    types.add(jass)
    out, depth, in_globals, locals_done, local_types = [], 0, False, True, {}

    def emit(text: str) -> None:
        out.append(("    " * depth if indented else "") + text)

    for number, source in enumerate(jass.replace("\r\n", "\n").split("\n"), 1):
        if source.startswith(RAW):
            out.append(source[1:])
            locals_done = True
            continue
        line = source.strip()
        if not line or line.startswith("//"):
            continue
        p = _Printer(types, local_types)
        try:
            if line in ("globals", "endglobals"):
                in_globals = line == "globals"
            elif in_globals:
                jass_type, array, name, value = _GLOBAL.match(line).groups()
                if array:
                    out.append(f"{name} = __jarray({DEFAULTS[jass_type]})" if jass_type in DEFAULTS else f"{name} = {{}}")
                else:
                    out.append(f"{name} = " + (('""' if jass_type == "string" else "nil") if value is None
                                               else p.value(value, jass_type)))
            elif m := _FUNCTION.match(line):
                name, takes, _ = m.groups()
                local_types.clear()
                if takes != "nothing":
                    local_types.update((x.split()[1], x.split()[0]) for x in takes.split(","))
                out.append(f"function {name}({', '.join(local_types)})")
                depth, locals_done = 1, False
            elif m := _LOCAL.match(line):
                jass_type, array, name, value = m.groups()
                local_types[name] = jass_type
                if array:
                    emit(f"local {name} = __jarray({DEFAULTS[jass_type]})" if jass_type in DEFAULTS else f"local {name} = {{}}")
                else:
                    emit(f"local {name}" + (f" = {p.show(_parse(value), jass_type)}" if value is not None else ""))
            else:
                if not locals_done:
                    locals_done = True
                    if blank_after_locals and out and out[-1].lstrip().startswith("local "):
                        out.append("")
                if line == "endfunction":
                    depth = 0
                    out += ["end", ""]
                elif m := _SET.match(line):
                    name, index, value = m.groups()
                    emit(f"{name}[{p.show(_parse(index))}]" if index is not None else name)
                    out[-1] += f" = {p.value(value, p.var_type(name))}"
                elif line.startswith("call "):
                    emit(p.show(_parse(line[5:])))
                elif line.startswith(("if ", "elseif ")) and line.endswith(" then"):
                    keyword, condition = line.split(" ", 1)
                    depth -= keyword == "elseif"
                    emit(f"{keyword} ({_condition(p, condition[:-5])}) then")
                    depth += 1
                elif line == "else":
                    depth -= 1
                    emit("else")
                    depth += 1
                elif line in ("endif", "endloop"):
                    depth -= 1
                    emit("end")
                elif line == "loop":
                    emit("while (true) do")
                    depth += 1
                elif line.startswith("exitwhen "):
                    emit(f"if ({p.show(_parse(line[9:]))}) then break end")
                elif line == "return":
                    emit("return ")
                elif line.startswith("return "):
                    emit("return " + p.show(_parse(line[7:])))
                else:
                    raise ValueError("unsupported JASS statement")
        except (ValueError, AttributeError, KeyError, IndexError) as e:
            raise ValueError(f"war3map.j line {number}: cannot transpile {line[:80]!r}: {e}") from e
    return "\r\n".join(out) + "\r\n"
