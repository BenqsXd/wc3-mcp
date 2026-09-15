"""Trigger-dependent parts of an editor-generated war3map.j, from war3map.wtg + war3map.wct, and splice() that swaps
them into an existing script keeping every other byte. Exact on all local JASS corpus maps."""
import re

from ..formats import wtg
from ..gamedata.triggerdata import EVENT
from ..ops.gui import RAWCODE_TYPES, script_name
from .jass import BAR, JassGen

BANNER = "//" + "*" * 75


def banner(title: str) -> str:
    return f"{BANNER}\n//*\n//*  {title}\n//*\n{BANNER}\n"


def triggers(tf) -> list:
    return [e for e in tf.elements if isinstance(e, wtg.Trigger) and e.kind == wtg.TRIGGER]


def listed(t) -> bool:
    """Triggers that get a script section and an InitTrig call."""
    return bool(t.enabled) and not t.is_comment


def runs_on_init(t) -> bool:
    return listed(t) and not t.initially_off and bool(
        t.run_on_init or any(e.kind == EVENT and e.enabled and e.name == "MapInitializationEvent" for e in t.ecas))


# ---- globals ---------------------------------------------------------------------------------------------------
def declaration(jass_type: str, name: str, array: bool, value: str | None) -> str:
    if array:
        return f"    {jass_type + ' array':<23} {name}"
    return f"    {jass_type:<23} {name}" if value is None else f"    {jass_type:<23} {name:<26} = {value}"


def zero(jass_type: str) -> str | None:
    return {"integer": "0", "real": "0", "boolean": "false", "string": None}.get(jass_type, "null")


def user_globals(tf, td) -> str:
    if not tf.variables:
        return ""
    lines = ["    // User-defined"]
    for v in tf.variables:
        jt = td.base(v.type)
        lines.append(declaration(jt, "udg_" + v.name, bool(v.is_array), zero(jt)))
    return "\n".join(lines) + "\n\n"


def trigger_globals(tf) -> list[str]:
    """Every kind-8 trigger (disabled and comment ones too), first occurrence of each script name."""
    names = dict.fromkeys("gg_trg_" + script_name(t.name) for t in triggers(tf))
    return [declaration("trigger", n, False, "null") for n in names]


def initial_value(v, td, defaults) -> str | None:
    if not v.initialized:
        return defaults.get(v.type, '""' if v.type == "string" else None)
    preset = td.presets.get(v.initial)
    if preset is not None:
        return preset.code.replace("`", '"')
    if v.type in RAWCODE_TYPES:
        return f"'{v.initial}'"
    if td.base(v.type) == "string":
        return '"' + v.initial.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v.initial


def init_globals(tf, td) -> str:
    defaults = td.type_defaults
    body = ["    local integer i = 0"] if any(v.is_array for v in tf.variables) else []
    for v in tf.variables:
        value = initial_value(v, td, defaults)
        if value is None:
            continue
        if v.is_array:
            body += ["    set i = 0", "    loop", f"        exitwhen (i > {v.array_size})",
                     f"        set udg_{v.name}[i] = {value}", "        set i = i + 1", "    endloop", ""]
        else:
            body.append(f"    set udg_{v.name} = {value}")
    return "function InitGlobals takes nothing returns nothing\n" + "".join(x + "\n" for x in body) + "endfunction\n"


# ---- custom script and triggers ----------------------------------------------------------------------------------
def custom_script(ct) -> str:
    """The map header's section, placed right before the Triggers banner; absent when the header is empty."""
    if not ct.header:
        return ""
    return banner("Custom Script Code") + ct.header.replace("\r\n", "\n") + "\n"


def trigger_sections(tf, ct, td) -> str:
    gen = JassGen(td, {v.name: v for v in tf.variables})
    return "".join(gen.section(t, text) for t, text in zip(triggers(tf), ct.texts) if listed(t))


def init_custom_triggers(tf) -> str:
    calls = "".join(f"    call InitTrig_{script_name(t.name)}(  )\n" for t in triggers(tf) if listed(t))
    return f"{BAR}\nfunction InitCustomTriggers takes nothing returns nothing\n{calls}endfunction\n\n"


def run_initialization_triggers(tf) -> str:
    calls = "".join(f"    call ConditionalTriggerExecute( gg_trg_{script_name(t.name)} )\n"
                    for t in triggers(tf) if runs_on_init(t))
    return f"{BAR}\nfunction RunInitializationTriggers takes nothing returns nothing\n{calls}endfunction\n\n"


# ---- splice ----------------------------------------------------------------------------------------------------
def _crlf(text: str) -> str:
    return text.replace("\n", "\r\n")


TRIGGER_DECL = re.compile(r"    trigger +gg_trg_\w+ += null")
BEFORE_TRIGGERS = ("gg_rct_", "gg_cam_", "gg_snd_")     # generated globals declared ahead of the triggers


def _find(s: str, sub: str, start: int = 0) -> int:
    i = s.find(sub, start)
    if i < 0:
        raise ValueError(f"not an editor-generated war3map.j: {sub.strip()!r} not found")
    return i


def splice(original: str, tf, ct, td) -> str:
    """Regenerate globals (user-defined and gg_trg_ lines), InitGlobals, the header's Custom Script Code section and
    the Triggers section (sections, InitCustomTriggers, RunInitializationTriggers) of an editor-generated script."""
    o = _crlf(original.replace("\r\n", "\n")) if "\r\n" not in original else original
    g0 = _find(o, "\r\nglobals\r\n") + len("\r\nglobals\r\n")
    g1 = _find(o, "\r\nendglobals\r\n", g0 - 2) + 2
    lines = o[g0:g1].split("\r\n")[:-1]
    generated = lines[lines.index("    // Generated") + 1:] if "    // Generated" in lines else []
    generated = [x for x in generated if not TRIGGER_DECL.fullmatch(x)]
    at = next((k for k, x in enumerate(generated) if not (x.split() + ["", ""])[1].startswith(BEFORE_TRIGGERS)),
              len(generated))
    generated[at:at] = trigger_globals(tf)
    globals_text = user_globals(tf, td) + ("    // Generated\n" + "".join(x + "\n" for x in generated) if generated else "")

    i0 = _find(o, "\r\nfunction InitGlobals takes nothing returns nothing\r\n", g1) + 2
    i1 = _find(o, "\r\nendfunction\r\n", i0) + len("\r\nendfunction\r\n")

    trig_banner = _crlf(banner("Triggers") + "\n")
    t0 = _find(o, trig_banner, i1)
    csc = _crlf(banner("Custom Script Code"))
    first_csc = _find(o, csc, i1)
    last_csc = o.rfind(csc, 0, t0)
    c0 = last_csc if last_csc != first_csc else t0

    ict = o.rfind(_crlf(f"{BAR}\nfunction InitCustomTriggers takes nothing returns nothing\n"))
    if ict < t0:
        raise ValueError("not an editor-generated war3map.j: InitCustomTriggers not found")
    end = _find(o, "\r\nendfunction\r\n\r\n", ict) + len("\r\nendfunction\r\n\r\n")
    rit = _crlf(f"{BAR}\nfunction RunInitializationTriggers takes nothing returns nothing\n")
    if o.startswith(rit, end):
        end = _find(o, "\r\nendfunction\r\n\r\n", end) + len("\r\nendfunction\r\n\r\n")
    triggers_text = trigger_sections(tf, ct, td) + init_custom_triggers(tf) + run_initialization_triggers(tf)

    return (o[:g0] + _crlf(globals_text) + o[g1:i0] + _crlf(init_globals(tf, td)) + o[i1:c0]
            + _crlf(custom_script(ct)) + trig_banner + _crlf(triggers_text) + o[end:])
