"""GUI triggers -> the World Editor's JASS: one trigger's section of war3map.j, byte-identical to the editor's output
(28,874 of 28,879 local corpus triggers; the rest contradict their stored trigger data)."""
from ..formats.wtg import ECA, FUNCTION, PRESET, STRING, VARIABLE
from ..gamedata.triggerdata import ACTION, CALL, CONDITION, EVENT
from ..ops.gui import RAWCODE_TYPES, script_name, var_type

BAR = "//" + "=" * 75
CALLBACKS = {"ForGroupMultiple", "ForForceMultiple", "EnumDestructablesInRectAllMultiple",
             "EnumDestructablesInCircleBJMultiple", "EnumItemsInRectBJMultiple"}
BOOLEAN_CALLS = ("GetBooleanAnd", "GetBooleanOr")
BLOCKS = {"IfThenElseMultiple", "ForLoopAMultiple", "ForLoopBMultiple", "ForLoopVarMultiple"} | CALLBACKS


class JassGen:
    def __init__(self, td, variables: dict):
        self.td, self.variables = td, variables

    # ---- structure -------------------------------------------------------------------------------------------
    def add(self, name: str, returns: str, body: list[str]) -> str:
        self.functions.append(f"function {name} takes nothing returns {returns}\n"
                              + "".join(line + "\n" for line in body) + "endfunction\n")
        return name

    def section(self, t, text) -> str:
        self.name = script_name(t.name)
        self.prefix = f"Trig_{self.name}"
        self.functions = []
        head = [BAR, f"// Trigger: {t.name}"]
        first, *rest = t.description.split("\r\n")   # the first line is kept even when empty; later empty lines drop
        lines = [first] + [line for line in rest if line]
        if t.description:
            head.append("//")
            head += ["// " + line for line in lines]
        head.append(BAR)
        if t.custom_text:
            return "\n".join(head) + "\n" + (text or "").replace("\r\n", "\n") + "\n"
        conditions = [(i, e) for i, e in enumerate(t.ecas, 1) if e.kind == CONDITION and e.enabled]
        actions = [(i, e) for i, e in enumerate(t.ecas, 1) if e.kind == ACTION and e.enabled]
        events = [e for e in t.ecas if e.kind == EVENT and e.enabled]
        if conditions:
            self.add(f"{self.prefix}_Conditions", "boolean", self.condition_body(conditions))
        body = []
        for i, e in actions:
            body += self.statement(e, f"Func{i:03d}", 1)
        self.add(f"{self.prefix}_Actions", "nothing", body)
        trig = f"gg_trg_{self.name}"
        init = [f"    set {trig} = CreateTrigger(  )"]
        if t.initially_off:
            init.append(f"    call DisableTrigger( {trig} )")
        for e in events:
            if e.name == "MapInitializationEvent":
                continue
            fn = self.td.function(EVENT, e.name)
            args = [trig] + [self.expr(p, a, "", k) for k, (p, a) in enumerate(zip(e.params, fn.args), 1)]
            init.append(f"    call {fn.script_name or e.name}( {', '.join(args)} )")
        if conditions:
            init.append(f"    call TriggerAddCondition( {trig}, Condition( function {self.prefix}_Conditions ) )")
        init.append(f"    call TriggerAddAction( {trig}, function {self.prefix}_Actions )")
        out = "\n".join(head) + "\n" + "".join(f + "\n" for f in self.functions)
        return out + f"{BAR}\nfunction InitTrig_{self.name} takes nothing returns nothing\n" + "\n".join(init) + "\nendfunction\n\n"

    def condition_body(self, numbered, any_of: bool = False) -> list[str]:
        body = []
        for path, e in numbered:
            body += self.test(path if isinstance(path, str) else f"Func{path:03d}", e, any_of)
        body.append("    return false" if any_of else "    return true")
        return body

    def test(self, path: str, e, any_of: bool = False) -> list[str]:
        text, wrap = self.condition(e.name, e.params, e.children, path)
        if e.name not in ("AndMultiple", "OrMultiple"):
            self.leftovers(e, path, 1)
        test = f"( {text} )" if wrap else text
        if any_of:
            return [f"    if ( {test} ) then", "        return true", "    endif"]
        return [f"    if ( not {test} ) then", "        return false", "    endif"]

    # ---- statements ------------------------------------------------------------------------------------------
    @staticmethod
    def numbered(e, group, path) -> list:
        """Enabled children of one block, numbered by position in the parent's whole child list (file order)."""
        return [(f"{path}Func{j:03d}", c) for j, c in enumerate(e.children, 1) if c.group == group and c.enabled]

    def children(self, e, group, path, depth) -> list[str]:
        out = []
        for where, c in self.numbered(e, group, path):
            out += self.statement(c, where, depth)
        return out

    def statement(self, e, path: str, depth: int) -> list[str]:
        out = self._statement(e, path, depth)
        if e.name not in BLOCKS:
            self.leftovers(e, path, depth)
        return out

    def leftovers(self, e, path: str, depth: int) -> None:
        """Children kept under a non-block function (after its block function was replaced): the editor still
        emits their helper functions, numbered by file position, but no statement or test for them."""
        for j, c in enumerate(e.children, 1):
            if c.enabled:
                where = f"{path}Func{j:03d}"
                self.test(where, c) if c.kind == CONDITION else self.statement(c, where, depth + 1)

    def _statement(self, e, path: str, depth: int) -> list[str]:
        ind = "    " * depth
        name = e.name
        fn = self.td.function(ACTION, name)
        if name == "SetVariable":
            vt = var_type(e.params[0].value, self.variables) or "?"
            target = self.var(e.params[0], f"{path}001")
            return [f"{ind}set {target} = {self.expr(e.params[1], vt, path, 2)}"]
        if name == "CustomScriptCode":
            return [ind + e.params[0].value]
        if name == "CommentString":
            return [ind + "// " + (e.params[0].value or "ERROR")]   # empty text: one corpus sample (ROC Orc01)
        if name == "ReturnAction":
            return [ind + "return"]
        if name == "WaitForCondition":
            helper = self.condition_helper(e.params[0].call, f"{path}001")
            return [f"{ind}loop", f"{ind}    exitwhen ( {helper}() )",
                    f"{ind}    call TriggerSleepAction(RMaxBJ(bj_WAIT_FOR_COND_MIN_INTERVAL, "
                    f"{self.expr(e.params[1], 'real', path, 2)}))", f"{ind}endloop"]
        if name == "IfThenElse":
            helper = self.condition_helper(e.params[0].call, f"{path}001")
            then = self.statement(self.as_eca(e.params[1]), f"{path}002", depth + 1)
            other = self.statement(self.as_eca(e.params[2]), f"{path}003", depth + 1)
            return [f"{ind}if ( {helper}() ) then", *then, f"{ind}else", *other, f"{ind}endif"]
        if name in ("ForLoopA", "ForLoopB", "ForLoopVar"):
            if name == "ForLoopVar":
                index = self.var(e.params[0], f"{path}001")
                out = [f"{ind}set {index} = {self.expr(e.params[1], 'integer', path, 2)}", f"{ind}loop",
                       f"{ind}    exitwhen {index} > {self.expr(e.params[2], 'integer', path, 3)}"]
            else:
                letter = name[-1]
                index, end = f"bj_forLoop{letter}Index", f"bj_forLoop{letter}IndexEnd"
                out = [f"{ind}set {index} = {self.expr(e.params[0], 'integer', path, 1)}",
                       f"{ind}set {end} = {self.expr(e.params[1], 'integer', path, 2)}",
                       f"{ind}loop", f"{ind}    exitwhen {index} > {end}"]
            code = len(e.params)
            out += self.statement(self.as_eca(e.params[code - 1]), f"{path}{code:03d}", depth + 1)
            return out + [f"{ind}    set {index} = {index} + 1", f"{ind}endloop"]
        if name == "IfThenElseMultiple":
            # helpers come out in the file order of the children (any block), the block's own C function last
            parts = {0: [], 1: [], 2: []}
            for j, c in enumerate(e.children, 1):
                if c.enabled and c.group in parts:
                    where = f"{path}Func{j:03d}"
                    parts[c.group] += self.test(where, c) if c.group == 0 else self.statement(c, where, depth + 1)
            helper = self.add(f"{self.prefix}_{path}C", "boolean", parts[0] + ["    return true"])
            return [f"{ind}if ( {helper}() ) then", *parts[1], f"{ind}else", *parts[2], f"{ind}endif"]
        if name == "AddTriggerEvent":
            c = e.params[1].call
            event = self.td.function(EVENT, c.name)
            args = [self.expr(e.params[0], "trigger", path, 1)] + [
                self.expr(p, a, f"{path}002", k) for k, (p, a) in enumerate(zip(c.params or [], event.args), 1)]
            return [f"{ind}call {event.script_name or c.name}( {', '.join(args)} )"]
        if name in ("ForLoopAMultiple", "ForLoopBMultiple", "ForLoopVarMultiple"):
            if name == "ForLoopVarMultiple":
                index = self.var(e.params[0], f"{path}001")
                out = [f"{ind}set {index} = {self.expr(e.params[1], 'integer', path, 2)}", f"{ind}loop",
                       f"{ind}    exitwhen {index} > {self.expr(e.params[2], 'integer', path, 3)}"]
            else:
                letter = name[len("ForLoop")]
                index, end = f"bj_forLoop{letter}Index", f"bj_forLoop{letter}IndexEnd"
                out = [f"{ind}set {index} = {self.expr(e.params[0], 'integer', path, 1)}",
                       f"{ind}set {end} = {self.expr(e.params[1], 'integer', path, 2)}",
                       f"{ind}loop", f"{ind}    exitwhen {index} > {end}"]
            out += self.children(e, 0, path, depth + 1)
            return out + [f"{ind}    set {index} = {index} + 1", f"{ind}endloop"]
        if name in CALLBACKS:
            args = [self.expr(p, a, path, k) for k, (p, a) in enumerate(zip(e.params, fn.args), 1)]
            helper = self.add(f"{self.prefix}_{path}A", "nothing", self.children(e, 0, path, 1))
            return [f"{ind}call {fn.script_name or name}( {', '.join(args + ['function ' + helper])} )"]
        args = [self.expr(p, a, path, k) for k, (p, a) in enumerate(zip(e.params, fn.args), 1)]
        return [f"{ind}call {fn.script_name or name}( {', '.join(args)} )"]

    @staticmethod
    def as_eca(p) -> ECA:
        return ECA(ACTION, p.call.name, 1, p.call.params or [])

    # ---- expressions -----------------------------------------------------------------------------------------
    def condition(self, name: str, params, children, path: str) -> tuple[str, bool]:
        """A condition's text and whether it is shown in parentheses."""
        params = params or []
        fn = self.td.function(CONDITION, name)
        if name.startswith("OperatorCompare"):
            return self.infix(fn, params, path), True
        if name in BOOLEAN_CALLS:
            helpers = [self.condition_helper(p.call, f"{path}{k:03d}") + "()" for k, p in enumerate(params, 1)]
            return f"{name}( {', '.join(helpers)} )", False
        if name in ("AndMultiple", "OrMultiple"):
            numbered = [(f"{path}Func{j:03d}", c) for j, c in enumerate(children, 1) if c.enabled]
            helper = self.add(f"{self.prefix}_{path}C", "boolean", self.condition_body(numbered, name == "OrMultiple"))
            return f"{helper}()", False
        return self.call_text(fn, name, params, path), False

    def condition_helper(self, call, path: str) -> str:
        text, wrap = self.condition(call.name, call.params, [], path)
        return self.add(f"{self.prefix}_{path}", "boolean", ["    return " + (f"( {text} )" if wrap else text)])

    def infix(self, fn, params, path: str) -> str:
        types = list(fn.args) if fn else [""] * len(params)
        a, op, b = (self.expr(p, t, path, k) for k, (p, t) in enumerate(zip(params, types), 1))
        return f"{a} {op} {b}"

    def call_text(self, fn, name: str, params, path: str) -> str:
        types = list(fn.args) if fn else [""] * len(params)
        if name.startswith("OperatorCompare") or name in ("OperatorInt", "OperatorReal"):
            return f"( {self.infix(fn, params, path)} )"
        if name == "OperatorString":
            a, b = (self.expr(p, t, path, k) for k, (p, t) in enumerate(zip(params, types), 1))
            return f"( {a} + {b} )"
        if name in BOOLEAN_CALLS:
            return self.condition(name, params, [], path)[0]
        args = [self.expr(p, t, path, k) for k, (p, t) in enumerate(zip(params, types), 1)]
        return f"{(fn.script_name if fn else None) or name}({', '.join(args)})"

    def var(self, p, path: str) -> str:
        text = p.value if p.value.startswith("gg_") else "udg_" + p.value
        return f"{text}[{self.expr(p.index, 'integer', path, 1)}]" if p.index is not None else text

    def literal(self, value: str, expected: str) -> str:
        if expected in RAWCODE_TYPES:
            return f"'{value}'"
        if expected != "scriptcode" and self.td.base(expected) == "string":
            return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return value

    def expr(self, p, expected: str, path: str, index: int) -> str:
        if p.type == STRING:
            return self.literal(p.value, expected)
        if p.type == PRESET:
            preset = self.td.presets.get(p.value)
            return (preset.code if preset else p.value).replace("`", '"')
        if p.type == VARIABLE:
            text = self.var(p, f"{path}{index:03d}")
            return f'"{text}"' if expected.startswith("VarAsString_") else text
        if p.type == FUNCTION and p.call is not None:
            c, here = p.call, f"{path}{index:03d}"
            if c.kind == CONDITION:
                return f"Condition(function {self.condition_helper(c, here)})"
            if c.kind == ACTION:
                return f"function {self.add(f'{self.prefix}_{here}', 'nothing', self.statement(self.as_eca(p), here, 1))}"
            return self.call_text(self.td.function(CALL, c.name), c.name, c.params or [], here)
        return "null"
