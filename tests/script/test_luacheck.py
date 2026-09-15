"""Lua 5.3 syntax checker tests: grammar suites, error positions, sample-map scripts and mutations."""
import random

import pytest

from corpus import open_sample, sample_map_ids
from wc3mcp.script.luacheck import check, tokenize

LUA = {m: s.decode("utf-8") for m in sample_map_ids() for s in [open_sample(m).read("war3map.lua")] if s is not None}


VALID = [
    # chunks, empty statements, locals, assignment
    "", ";;;", "local a", "local a, b, c = 1, 2", "a = 1", "a, b = b, a",
    "a.b.c = 1", "a[1][2] = 3", "a.b['c'].d = f()", "(a).b = 1", "(a)[1], b.c = 1, 2",
    "local a = {} a.b = 1 f() g()",
    # calls: parens, string, long string, table args, methods, chains
    "f()", "f 'str'", 'f "str"', "f [[long]]", "f {1, 2}", "f\n(g)",
    "obj:method(1)", "obj:method 'x'", "obj:method {x = 1}", "a.b:c(d)(e)[f]:g()",
    "f()()", "local x = (f())", '("x"):rep(3)', "x = a.b[c](d):e 'f' {g}", "f(function() end, {})",
    # blocks and control flow
    "do end", "do local x = 1 end", "do ;;; end", "while true do break end",
    "while x do if y then break end end", "repeat local x = 1 until x == 1",
    "repeat if x then break end until true", "if a then elseif b then else end",
    "if a then b() end", "if x then return end",
    "for i = 1, 10 do end", "for i = 10, 1, -1 do end", "for k, v in pairs(t) do end",
    "for k in next, t do end", "for i = 1, 2 do local function g() return i end end",
    # functions, varargs, methods
    "function f() end", "function a.b.c:d(x, y) return self end", "function f(...) return ... end",
    "function f(a, b, ...) local t = {...} end", "local function f() return f() end",
    "local f = function(x) return x end", "x = function() end", "return function() end",
    "local function f(...) return select('#', ...) end", "f{...}", "local t = {f(), ...}",
    # return forms
    "return", "return;", "return 1, 2, 3", "do return end", "function f() return end",
    # labels, goto (5.3 visibility rules)
    "::top:: goto top", "goto done; ::done::", "do goto a end ::a::", "::a:: do ::a:: end",
    "for i = 1, 3 do if i == 2 then goto continue end ::continue:: end",
    "while true do goto out end ::out::", "::a:: ::b:: ; ::c::", "if a then goto l end ::l::",
    "function f() goto x ::x:: end ::x::",
    # table constructors
    "local t = {}", "local t = {1, 2, 3,}", "local t = {x = 1; y = 2; [3] = 4,}",
    "local t = {[1] = 1, 'a', b = {}}", "x = {[f()] = 1, [ [[s]] ] = 2}",
    # numbers
    "local n = 3, 3.0, 3.1416, 314.16e-2, 0.31416E1, 34e1, .5, 5., 1e+10",
    "local n = 0xff, 0x0.1E, 0xA23p-4, 0X1.921FB54442D18P+1, 0x.8p1, 0xffffffffffffffffffff",
    # strings and escapes
    'local s = "\\a\\b\\f\\n\\r\\t\\v\\\\\\"\\\'"', 'local s = "\\x41\\65\\u{48}\\u{10FFFF}\\u{0000000041}"',
    'local s = "a\\z   \n   b"', "local s = 'line1\\\nline2'", "local s = 'crlf\\\r\nnext'",
    'local s = "\\0\\00\\000\\255"', "local s = [==[ ]] ]=] ]==]", "x = [[\nfirst newline skipped]]",
    "-- héllo\nx = 'ünïcode'",
    # comments
    "--[==[ \n ]] \n]==] x = 1", "-- comment\nx = 1 -- trailing", "--[ not long\nx = 1",
    "--[=x not long\nx = 1", "--[[ ]]--[[ ]]x = 1", "x = 1 --[[ inline ]] + 2",
    # operators and precedence
    "x = 1 + 2 - 3 * 4 / 5 // 6 % 7 ^ 8 .. 'a'", "x = 1 & 2 | 3 ~ 4 << 5 >> 6 ~ ~7",
    "x = a == b, a ~= b, a < b, a <= b, a > b, a >= b", "x = not a and b or c",
    "x = -#t, - - 1, not not a", "x = 2^-3^2", "x = a..b..c", "x = #'abc'", "x = ((a))",
    "x = 1//2", "x = a.b.c.d.e()",
    # line endings, deep but legal nesting
    "local a = 1\r\nlocal b = 2\r\n", "a = 1\n\rb = 2\r\rc = 3",
    "x = " + "(" * 150 + "1" + ")" * 150,
]

INVALID = [  # (source, expected line, message fragment)
    ("x = ", 1, "unexpected symbol near <eof>"),
    ("if x then", 1, "'end' expected near <eof>"),
    ("if x then\n\n", 3, "'end' expected (to close 'if' at line 1) near <eof>"),
    ("function f()\nreturn 1\n", 3, "'end' expected (to close 'function' at line 1)"),
    ("f(", 1, "unexpected symbol near <eof>"),
    ("f(1\nx = 2", 2, "')' expected (to close '(' at line 1) near 'x'"),
    ("x = 1 +", 1, "unexpected symbol near <eof>"),
    ("local = 1", 1, "<name> expected near '='"),
    ("local function 1() end", 1, "<name> expected near '1'"),
    ("local function(x) end", 1, "<name> expected near '('"),
    ("x", 1, "syntax error near <eof>"),
    ("x\ny = 1", 2, "syntax error near 'y'"),
    ("f() = 1", 1, "syntax error near '='"),
    ("(a) = 1", 1, "syntax error near '='"),
    ("a, f() = 1, 2", 1, "syntax error near '='"),
    ("a.b:c = 1", 1, "function arguments expected near '='"),
    ("t:m", 1, "function arguments expected near <eof>"),
    ("return 1\nx = 2", 2, "'<eof>' expected near 'x'"),
    ("do return 1 x = 2 end", 1, "'end' expected near 'x'"),
    ("return return", 1, "unexpected symbol near 'return'"),
    ("for i = 1 do end", 1, "',' expected near 'do'"),
    ("for i do end", 1, "'=' or 'in' expected near 'do'"),
    ("for 1 = 1, 2 do end", 1, "<name> expected near '1'"),
    ("for k, v pairs(t) do end", 1, "'in' expected near 'pairs'"),
    ("for i = 1, 2 end", 1, "'do' expected near 'end'"),
    ("for i = 1, 2, 3, 4 do end", 1, "'do' expected near ','"),
    ("while true end", 1, "'do' expected near 'end'"),
    ("repeat x = 1", 1, "'until' expected near <eof>"),
    ("repeat\nuntil", 2, "unexpected symbol near <eof>"),
    ("if x end", 1, "'then' expected near 'end'"),
    ("if x then else elseif y then end", 1, "'end' expected near 'elseif'"),
    ("if x then\nelse\nelse\nend", 3, "'end' expected (to close 'if' at line 1) near 'else'"),
    ("else", 1, "'<eof>' expected near 'else'"),
    ("end", 1, "'<eof>' expected near 'end'"),
    ("until x", 1, "'<eof>' expected near 'until'"),
    ("while x do\n  y()\nuntil z", 3, "'end' expected (to close 'while' at line 1) near 'until'"),
    ("function f(1) end", 1, "<name> or '...' expected near '1'"),
    ("function f(..., a) end", 1, "')' expected near ','"),
    ("function f(a,) end", 1, "<name> or '...' expected near ')'"),
    ("function a:b.c() end", 1, "'(' expected near '.'"),
    ("local function f.g() end", 1, "'(' expected near '.'"),
    ("x = function end", 1, "'(' expected near 'end'"),
    ("function f() return ... end", 1, "cannot use '...' outside a vararg function near '...'"),
    ("function f(a)\n  local t = {...}\nend", 2, "cannot use '...' outside a vararg function"),
    ("local t = {a = }", 1, "unexpected symbol near '}'"),
    ("local t = {[1] 2}", 1, "'=' expected near '2'"),
    ("local t = {1 2}", 1, "'}' expected near '2'"),
    ("local t = {1,,2}", 1, "unexpected symbol near ','"),
    ("x = {", 1, "unexpected symbol near <eof>"),
    ("x = {\n1,\n2\n", 4, "'}' expected (to close '{' at line 1) near <eof>"),
    ("x = t[1", 1, "']' expected near <eof>"),
    ("x = t[]", 1, "unexpected symbol near ']'"),
    ("f(a,)", 1, "unexpected symbol near ')'"),
    ("x = 1 == == 2", 1, "unexpected symbol near '=='"),
    ("x = a != b", 1, "unexpected symbol near '!'"),
    ("x = @", 1, "unexpected symbol near '@'"),
    ("x = not", 1, "unexpected symbol near <eof>"),
    ("x = 1 // ", 1, "unexpected symbol near <eof>"),
    ("x = 1\ny = = 2", 2, "unexpected symbol near '='"),
    ("a.1 = 2", 1, "syntax error near '.1'"),
    ("local a, = 1", 1, "<name> expected near '='"),
    ("local x <const> = 1", 1, "unexpected symbol near '<'"),
    ("goto = 1", 1, "<name> expected near '='"),
    ("x = 'a' 'b'", 1, "unexpected symbol near ''b''"),
    ("goto 1", 1, "<name> expected near '1'"),
    ("x = 1 y = 2 z", 1, "syntax error near <eof>"),
    # lexical errors
    ("x = 'abc", 1, "unfinished string near <eof>"),
    ('x = "abc\ny"', 1, "unfinished string near '\"abc'"),
    ("x = 'abc\\", 1, "unfinished string near <eof>"),
    ('x = "a\\qb"', 1, "invalid escape sequence near '\\q'"),
    ('x = "\\x4g"', 1, "hexadecimal digit expected"),
    ('x = "\\256"', 1, "decimal escape too large"),
    ('x = "\\u{110000}"', 1, "UTF-8 value too large"),
    ('x = "\\u41"', 1, "missing '{'"),
    ('x = "\\u{41"', 1, "missing '}'"),
    ('x = "\\u{}"', 1, "hexadecimal digit expected"),
    ('x = "ok\\z\n\n  \\q"', 3, "invalid escape sequence"),
    ("x = [[abc", 1, "unfinished long string near <eof>"),
    ("x = 1\n--[==[ comment ]]\ny = 2", 2, "unfinished long comment near <eof>"),
    ("x = [=abc", 1, "invalid long string delimiter near '[='"),
    ("x = 3..2", 1, "malformed number near '3..2'"),
    ("x = 0x", 1, "malformed number near '0x'"),
    ("x = 1e", 1, "malformed number near '1e'"),
    ("x = 12abc", 1, "malformed number near '12abc'"),
    ("x = 0x1p", 1, "malformed number near '0x1p'"),
    ("x = 1.2.3", 1, "malformed number near '1.2.3'"),
    ("x = = 1 'unterminated", 1, "unexpected symbol near '='"),  # parse error wins: lexer is lazy
    # goto / break / labels
    ("goto nowhere", 1, "no visible label 'nowhere' for <goto> at line 1"),
    ("break", 1, "<break> at line 1 not inside a loop"),
    ("x = 1\ndo break end", 2, "<break> at line 2 not inside a loop"),
    ("function f()\n  break\nend\nwhile 1 do end", 2, "not inside a loop"),
    ("::a:: ::a::", 1, "label 'a' already defined on line 1"),
    ("::a::\nx = 1\n::a::", 3, "label 'a' already defined on line 1"),
    ("do ::a:: end goto a", 1, "no visible label 'a'"),
    ("goto a; do ::a:: end", 1, "no visible label 'a'"),
    ("function f() ::x:: end\ngoto x", 2, "no visible label 'x'"),
    ("::x::\nfunction f()\n  goto x\nend", 3, "no visible label 'x' for <goto> at line 3"),
    # line counting with CR, CRLF and LFCR breaks
    ("a = 1\r\nb = 2\r\nc = = 3", 3, "unexpected symbol near '='"),
    ("a = 1\n\rb = = 2", 2, "unexpected symbol near '='"),
    ("a = 1\r\rb = = 2", 3, "unexpected symbol near '='"),
    ("x = [[\n\n]] y", 3, "syntax error near <eof>"),
    # nesting limit (LUAI_MAXCCALLS = 200)
    ("x = " + "(" * 300 + "1" + ")" * 300, 1, "too many C levels (limit is 200) in main function"),
]


@pytest.mark.parametrize("src", VALID)
def test_valid(src):
    assert check(src) == []


@pytest.mark.parametrize("src,line,fragment", INVALID)
def test_invalid(src, line, fragment):
    errors = check(src)
    assert len(errors) == 1, src
    assert errors[0]["line"] == line, errors
    assert fragment in errors[0]["message"], errors


def test_suite_sizes():
    assert len(VALID) >= 60 and len(INVALID) >= 60


def test_columns():
    assert check("x = 1\n  y = = 2") == [{"line": 2, "column": 7, "message": "unexpected symbol near '='"}]
    assert check("x = 'a\\qb'")[0]["column"] == 7  # points at the backslash
    assert check("\tx = [[abc")[0]["column"] == 6  # points at the long bracket


@pytest.mark.skipif(not LUA, reason="no Lua sample maps")
def test_corpus_clean():
    failures = {m: e for m, src in LUA.items() for e in [check(src)] if e}
    assert failures == {}


# -- mutation test ----------------------------------------------------------------
STRAY = ["end", ")", "(", "=", ",", "then", "do", "local", "..", "and", "}", "{", "]",
         "x", "1", "'s'", "function", "return", "until", "else", "::", "goto", "+", "not", ";", "."]
KINDS = ["delete 'end'", "drop ')'", "stray token", "unterminated string", "unterminated long comment"]


def mutations(count=200, seed=20260914):
    """Deterministic mutations: (kind, path, line, description, mutated source)."""
    rng = random.Random(seed)
    cache = {}
    for n in range(count):
        kind = KINDS[n % len(KINDS)]
        path = sorted(LUA)[rng.randrange(len(LUA))]
        if path not in cache:
            src = LUA[path]
            cache[path] = (src, tokenize(src))
        src, toks = cache[path]
        if kind == "delete 'end'":
            t = rng.choice([t for t in toks if t[0] == "end"])
            new, pos, desc = src[:t[1]] + src[t[2]:], t[1], "deleted 'end'"
        elif kind == "drop ')'":
            t = rng.choice([t for t in toks if t[0] == ")"])
            new, pos, desc = src[:t[1]] + src[t[2]:], t[1], "deleted ')'"
        elif kind == "stray token":
            t = rng.choice(toks[:-1])
            s = rng.choice(STRAY)
            new, pos, desc = src[:t[1]] + s + " " + src[t[1]:], t[1], "inserted %r before %r" % (s, src[t[1]:t[2]])
        elif kind == "unterminated string":
            t = rng.choice([t for t in toks if t[0] == "<string>" and src[t[1]] in "'\""])
            new, pos, desc = src[:t[2] - 1] + src[t[2]:], t[1], "removed closing quote of " + src[t[1]:t[2]]
        else:
            t = rng.choice(toks)
            new, pos, desc = src[:t[1]] + "--[[" + src[t[1]:], t[1], "inserted '--[[' before %r" % src[t[1]:t[2]]
        yield kind, path, src.count("\n", 0, pos) + 1, desc, new


def run_mutations():
    results = []
    for kind, path, line, desc, new in mutations():
        results.append((kind, path, line, desc, check(new)))
    return results


@pytest.mark.skipif(not LUA, reason="no Lua sample maps")
def test_mutations():
    results = run_mutations()
    assert len(results) == 200
    missed = [r for r in results if not r[4]]
    # Structural mutations can never yield valid Lua; only stray tokens may (e.g. ';', 'not').
    assert all(r[0] == "stray token" for r in missed), missed
    assert len(missed) <= 20, missed
