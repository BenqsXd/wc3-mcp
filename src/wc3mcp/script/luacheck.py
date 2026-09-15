"""Pure-Python Lua 5.3 syntax checker (stdlib only).

check(source) -> [] when the chunk compiles, else [{"line", "column", "message"}]
holding the FIRST error, like luac. Mirrors llex.c/lparser.c of Lua 5.3: the lexer
is driven lazily (a lexical error after an earlier syntax error is not reported) and
messages use Lua's wording ("'end' expected (to close 'if' at line 3) near <eof>").
Also reports the compile-time checks of lparser.c that need no code generation:
'...' outside a vararg function, duplicate label in one block (5.3 rule), goto
without a visible label, break outside a loop, nesting deeper than 200 C levels.
Positions are 1-based; \n, \r, \r\n and \n\r each count as one line break (llex.c).
Deliberate differences from luac: lexical errors inside a string/long bracket point
at the token start (luac: where it gave up); goto/break errors point at the goto
(luac: the end of the enclosing function).
ponytail: no 200-locals/255-upvalues/registers limits and no "jumps into the scope
of local" check; add them if generated code can ever hit them.
"""
import bisect
import re
import sys

KEYWORDS = frozenset(
    "and break do else elseif end false for function goto if in local nil not or "
    "repeat return then true until while".split())

# One token per match; the prefix skips whitespace and short comments.
_TOKEN = re.compile(r"""(?:[ \t\f\v\r\n]+|--(?!\[=*\[)[^\r\n]*)*(?:
 (?P<name>[A-Za-z_][A-Za-z0-9_]*)
|(?P<num>\.?0[xX](?:[pP][+-]?|[0-9a-fA-F.])*|\.?[0-9](?:[eE][+-]?|[0-9a-fA-F.])*)
|(?P<lcom>--\[=*\[)
|(?P<lstr>\[=*\[)
|(?P<badl>\[=+)
|(?P<str>["'])
|(?P<op>\.\.\.|\.\.|==|~=|<=|>=|<<|>>|//|::|[-+*/%^\#&~|<>=(){}\[\];:,.])
|(?P<eof>\Z)
|(?P<char>[\s\S]))""", re.X)
_NUMBER = re.compile(r"(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
                     r"|0[xX](?:[0-9a-fA-F]+\.?[0-9a-fA-F]*|\.[0-9a-fA-F]+)(?:[pP][+-]?[0-9]+)?")
_STR_STOP = {'"': re.compile(r'["\\\r\n]'), "'": re.compile(r"['\\\r\n]")}
_ESCAPE = re.compile(r"""\\(?:\r\n|\n\r|[abfnrtv\\"'\n\r]|z[ \t\n\v\f\r]*|x[0-9a-fA-F]{2}|(?P<d>[0-9]{1,3}))""")
_UTF8_ESCAPE = re.compile(r"\\u(\{)?([0-9a-fA-F]*)(\})?")
_NEWLINE = re.compile(r"\r\n|\n\r|\r|\n")

UNARY_PRIORITY = 12
UNARY = frozenset(("not", "-", "~", "#"))
BINARY = {  # token: (left, right) priority, lparser.c ORDER OPR
    "+": (10, 10), "-": (10, 10), "*": (11, 11), "%": (11, 11), "^": (14, 13),
    "/": (11, 11), "//": (11, 11), "&": (6, 6), "|": (4, 4), "~": (5, 5),
    "<<": (7, 7), ">>": (7, 7), "..": (9, 8), "==": (3, 3), "<": (3, 3),
    "<=": (3, 3), "~=": (3, 3), ">": (3, 3), ">=": (3, 3), "and": (2, 2), "or": (1, 1)}
LITERALS = frozenset(("<number>", "<string>", "nil", "true", "false"))
BLOCK_FOLLOW = frozenset(("else", "elseif", "end", "<eof>", "until"))
MAX_LEVELS = 200  # LUAI_MAXCCALLS


class LuaSyntaxError(Exception):
    def __init__(self, pos, message):
        super().__init__(message)
        self.pos, self.message = pos, message


def _near(text):
    return "'%s'" % (text if len(text) <= 40 else text[:37] + "...")


def _string_end(src, s):
    """End offset of the short string starting at s; raises LuaSyntaxError."""
    q, i, stop = src[s], s + 1, _STR_STOP[src[s]]
    while True:
        m = stop.search(src, i)
        if not m:
            raise LuaSyntaxError(s, "unfinished string near <eof>")
        i = m.start()
        if src[i] == q:
            return i + 1
        if src[i] != "\\":
            raise LuaSyntaxError(s, "unfinished string near " + _near(src[s:i]))
        e = _ESCAPE.match(src, i)
        if e:
            if e.group("d") and int(e.group("d")) > 255:
                raise LuaSyntaxError(i, "decimal escape too large near " + _near(e.group()))
            i = e.end()
            continue
        k = src[i + 1:i + 2]
        if not k:
            raise LuaSyntaxError(s, "unfinished string near <eof>")
        if k == "x":
            msg = "hexadecimal digit expected"
        elif k == "u":  # order of checks in readutf8esc
            brace, digits, close = _UTF8_ESCAPE.match(src, i).groups()
            msg = ("missing '{'" if not brace else "hexadecimal digit expected" if not digits
                   else "UTF-8 value too large" if int(digits, 16) > 0x10FFFF
                   else None if close else "missing '}'")
            if msg is None:
                i += 4 + len(digits)
                continue
        else:
            msg = "invalid escape sequence"
        raise LuaSyntaxError(i, "%s near %s" % (msg, _near(src[i:i + 2])))


def tokenize(src):
    """List of (type, start, end). A lexical error becomes ('<error>', pos, message)
    and ends the list; the parser raises it only when it reaches that token."""
    toks, pos, n, match = [], 0, len(src), _TOKEN.match
    append = toks.append
    try:
        while True:
            m = match(src, pos)
            kind = m.lastgroup
            s, pos = m.start(kind), m.end()
            if kind == "name":
                text = src[s:pos]
                append((text if text in KEYWORDS else "<name>", s, pos))
            elif kind == "op":
                append((src[s:pos], s, pos))
            elif kind == "num":
                if not _NUMBER.fullmatch(src, s, pos):
                    raise LuaSyntaxError(s, "malformed number near " + _near(src[s:pos]))
                append(("<number>", s, pos))
            elif kind == "str":
                pos = _string_end(src, s)
                append(("<string>", s, pos))
            elif kind == "lstr" or kind == "lcom":
                close = "]" + "=" * (pos - s - (2 if kind == "lstr" else 4)) + "]"
                j = src.find(close, pos)
                if j < 0:
                    raise LuaSyntaxError(s, "unfinished long %s near <eof>" % (
                        "string" if kind == "lstr" else "comment"))
                pos = j + len(close)
                if kind == "lstr":
                    append(("<string>", s, pos))
            elif kind == "eof":
                append(("<eof>", n, n))
                return toks
            elif kind == "badl":
                raise LuaSyntaxError(s, "invalid long string delimiter near " + _near(src[s:pos]))
            else:
                append((src[s], s, pos))
    except LuaSyntaxError as e:
        append(("<error>", e.pos, e.message))
        return toks


class _Parser:
    def __init__(self, src):
        self.src = src
        self.toks = tokenize(src)
        self.line_starts = [0] + [m.end() for m in _NEWLINE.finditer(src)]
        self.i = -1
        self.level = 0
        self.funcs = []   # [is_vararg, pos of 'function' or None for the main chunk]
        self.blocks = []  # [labels {name: pos}, pending gotos [(name, pos)], is_loop, is_function_root]
        self.next()

    def line(self, pos):
        return bisect.bisect_right(self.line_starts, pos)

    def next(self):
        self.i += 1
        self.t, self.s, self.e = self.toks[self.i]
        if self.t == "<error>":
            raise LuaSyntaxError(self.s, self.e)

    def error(self, msg):
        near = "<eof>" if self.t == "<eof>" else _near(self.src[self.s:self.e])
        raise LuaSyntaxError(self.s, "%s near %s" % (msg, near))

    def testnext(self, t):
        if self.t == t:
            self.next()
            return True
        return False

    def checknext(self, t):
        if self.t != t:
            self.error(("%s expected" if t == "<name>" else "'%s' expected") % t)
        self.next()

    def checkname(self):
        name = self.src[self.s:self.e]
        self.checknext("<name>")
        return name

    def checkmatch(self, what, who, pos):
        if self.t != what:
            line = self.line(pos)
            if line == self.line(self.s):
                self.error("'%s' expected" % what)
            self.error("'%s' expected (to close '%s' at line %d)" % (what, who, line))
        self.next()

    def enterlevel(self):
        self.level += 1
        if self.level > MAX_LEVELS:
            fpos = self.funcs[-1][1]
            self.error("too many C levels (limit is %d) in %s" % (MAX_LEVELS, "main function"
                       if fpos is None else "function at line %d" % self.line(fpos)))

    # -- blocks, labels, gotos (lparser.c enterblock/leaveblock/movegotosout) ----
    def open_func(self, vararg, pos):
        self.funcs.append([vararg, pos])
        self.blocks.append([{}, [], False, True])

    def enterblock(self, loop):
        self.blocks.append([{}, [], loop, False])

    def leaveblock(self):
        labels, gotos, loop, root = self.blocks.pop()
        pending = [g for g in gotos if g[0] not in labels and not (loop and g[0] == "break")]
        if not root:
            self.blocks[-1][1].extend(pending)
        elif pending:
            name, pos = pending[0]
            raise LuaSyntaxError(pos, ("<break> at line %d not inside a loop" if name == "break"
                                       else "no visible label '" + name + "' for <goto> at line %d")
                                 % self.line(pos))

    def close_func(self):
        self.leaveblock()
        self.funcs.pop()

    def block(self):
        self.enterblock(False)
        self.statlist()
        self.leaveblock()

    # -- statements --------------------------------------------------------------
    def chunk(self):
        self.open_func(True, None)
        self.statlist()
        if self.t != "<eof>":
            self.error("'<eof>' expected")
        self.close_func()

    def statlist(self):
        while self.t not in BLOCK_FOLLOW:
            if self.t == "return":
                self.statement()
                return  # 'return' must be the last statement
            self.statement()

    def statement(self):
        t, pos = self.t, self.s
        self.enterlevel()
        if t == ";":
            self.next()
        elif t == "if":
            self.test_then_block()
            while self.t == "elseif":
                self.test_then_block()
            if self.testnext("else"):
                self.block()
            self.checkmatch("end", "if", pos)
        elif t == "while":
            self.next()
            self.expr()
            self.enterblock(True)
            self.checknext("do")
            self.block()
            self.checkmatch("end", "while", pos)
            self.leaveblock()
        elif t == "do":
            self.next()
            self.block()
            self.checkmatch("end", "do", pos)
        elif t == "for":
            self.enterblock(True)
            self.next()
            self.checkname()
            if self.t == "=":
                self.next()
                self.expr()
                self.checknext(",")
                self.expr()
                if self.testnext(","):
                    self.expr()
            elif self.t == "," or self.t == "in":
                while self.testnext(","):
                    self.checkname()
                self.checknext("in")
                self.explist()
            else:
                self.error("'=' or 'in' expected")
            self.checknext("do")
            self.block()
            self.checkmatch("end", "for", pos)
            self.leaveblock()
        elif t == "repeat":
            self.enterblock(True)
            self.enterblock(False)
            self.next()
            self.statlist()
            self.checkmatch("until", "repeat", pos)
            self.expr()  # the condition is inside the body's scope
            self.leaveblock()
            self.leaveblock()
        elif t == "function":
            self.next()
            self.checkname()
            while self.testnext("."):
                self.checkname()
            if self.testnext(":"):
                self.checkname()
            self.body(pos)
        elif t == "local":
            self.next()
            if self.testnext("function"):
                self.checkname()
                self.body(pos)
            else:
                self.checkname()
                while self.testnext(","):
                    self.checkname()
                if self.testnext("="):
                    self.explist()
        elif t == "::":
            self.next()
            name = self.checkname()
            labels = self.blocks[-1][0]
            if name in labels:
                raise LuaSyntaxError(pos, "label '%s' already defined on line %d"
                                     % (name, self.line(labels[name])))
            self.checknext("::")
            labels[name] = pos
            while self.t == ";" or self.t == "::":  # skipnoopstat
                self.statement()
        elif t == "return":
            self.next()
            if self.t not in BLOCK_FOLLOW and self.t != ";":
                self.explist()
            self.testnext(";")
        elif t == "break" or t == "goto":
            self.next()
            self.blocks[-1][1].append(("break" if t == "break" else self.checkname(), pos))
        else:
            self.exprstat()
        self.level -= 1

    def test_then_block(self):
        self.next()  # skip 'if' / 'elseif'
        self.expr()
        self.checknext("then")
        self.block()

    def exprstat(self):
        kind = self.suffixedexp()
        if self.t == "=" or self.t == ",":
            while True:  # restassign: every target must be a variable
                if kind != "var":
                    self.error("syntax error")
                if not self.testnext(","):
                    break
                kind = self.suffixedexp()
            self.checknext("=")
            self.explist()
        elif kind != "call":
            self.error("syntax error")

    # -- expressions -------------------------------------------------------------
    def explist(self):
        self.expr()
        while self.testnext(","):
            self.expr()

    def expr(self, limit=0):  # lparser.c subexpr
        self.enterlevel()
        t = self.t
        if t in UNARY:
            self.next()
            self.expr(UNARY_PRIORITY)
        elif t in LITERALS:
            self.next()
        elif t == "...":
            if not self.funcs[-1][0]:
                self.error("cannot use '...' outside a vararg function")
            self.next()
        elif t == "{":
            self.constructor()
        elif t == "function":
            pos = self.s
            self.next()
            self.body(pos)
        else:
            self.suffixedexp()
        op = BINARY.get(self.t)
        while op and op[0] > limit:
            self.next()
            self.expr(op[1])
            op = BINARY.get(self.t)
        self.level -= 1

    def suffixedexp(self):
        """Returns 'var' (assignable), 'call' or 'exp' (parenthesized, not assignable)."""
        pos = self.s
        if self.t == "<name>":
            self.next()
            kind = "var"
        elif self.t == "(":
            self.next()
            self.expr()
            self.checkmatch(")", "(", pos)
            kind = "exp"
        else:
            self.error("unexpected symbol")
        while True:
            t = self.t
            if t == ".":
                self.next()
                self.checkname()
                kind = "var"
            elif t == "[":
                self.next()
                self.expr()
                self.checknext("]")
                kind = "var"
            elif t == ":":
                self.next()
                self.checkname()
                self.funcargs(pos)
                kind = "call"
            elif t == "(" or t == "<string>" or t == "{":
                self.funcargs(pos)
                kind = "call"
            else:
                return kind

    def funcargs(self, pos):
        if self.t == "(":
            self.next()
            if self.t != ")":
                self.explist()
            self.checkmatch(")", "(", pos)
        elif self.t == "{":
            self.constructor()
        elif self.t == "<string>":
            self.next()
        else:
            self.error("function arguments expected")

    def constructor(self):
        pos = self.s
        self.checknext("{")
        while self.t != "}":
            if self.t == "<name>" and self.toks[self.i + 1][0] == "=":
                self.next()
                self.next()
                self.expr()
            elif self.t == "[":
                self.next()
                self.expr()
                self.checknext("]")
                self.checknext("=")
                self.expr()
            else:
                self.expr()
            if not (self.testnext(",") or self.testnext(";")):
                break
        self.checkmatch("}", "{", pos)

    def body(self, pos):
        self.open_func(False, pos)
        self.checknext("(")
        if self.t != ")":
            while True:
                if self.t == "<name>":
                    self.next()
                elif self.t == "...":
                    self.next()
                    self.funcs[-1][0] = True
                    break
                else:
                    self.error("<name> or '...' expected")
                if not self.testnext(","):
                    break
        self.checknext(")")
        self.statlist()
        self.checkmatch("end", "function", pos)
        self.close_func()


def check(source):
    """Syntax-check a Lua 5.3 chunk. Returns [] or [{"line", "column", "message"}]."""
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, 6 * MAX_LEVELS + 1000))  # <= ~5 Python frames per C level
    p = None
    try:
        p = _Parser(source)
        p.chunk()
        return []
    except LuaSyntaxError as e:
        pos, msg = e.pos, e.message
    except RecursionError:  # not expected: MAX_LEVELS trips first
        pos, msg = (p.s if p else 0), "chunk has too many syntax levels"
    finally:
        sys.setrecursionlimit(old)
    starts = [0] + [m.end() for m in _NEWLINE.finditer(source)]
    line = bisect.bisect_right(starts, pos)
    return [{"line": line, "column": pos - starts[line - 1] + 1, "message": msg}]

