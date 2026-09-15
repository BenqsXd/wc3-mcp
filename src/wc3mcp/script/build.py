"""Trigger-dependent parts of an editor-generated war3map.j, from war3map.wtg + war3map.wct, and splice() that swaps
them into an existing script keeping every other byte. Exact on all local JASS corpus maps."""
import re

from ..formats import wtg
from ..gamedata.triggerdata import EVENT
from ..ops.gui import RAWCODE_TYPES, script_name
from . import mapinfo
from . import placed as placedgen
from . import world as worldgen
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


WORLD_SECTIONS = (("Sound Assets", "InitSounds"), ("Regions", "CreateRegions"), ("Cameras", "CreateCameras"))
ZONE = ("Random Groups", "Map Item Tables", "Unit Item Tables", "Destructible Item Tables", "Sound Assets",
        "Destructable Objects", "Items", "Unit Creation", "Regions", "Cameras")  # between the Custom Script Code sections
MAIN_ORDER = ("InitSounds", "CreateRegions", "CreateCameras", "InitUpgrades", "InitTechTree", "CreateAllDestructables",
              "CreateAllItems", "InitRandomGroups", "CreateAllUnits", "InitBlizzard")
PLACED_DECL = ("gg_unit_", "gg_item_", "gg_dest_")
_BANNER_LINE = re.compile(r"^//\*{75}\r\n//\*\r\n//\*  (.*)\r\n//\*\r\n//\*{75}\r\n", re.M)


def _trigger_start(o: str, after: int) -> tuple[int, int]:
    """(start of the header's Custom Script Code section or of the Triggers banner, start of the Triggers banner)"""
    t0 = _find(o, _crlf(banner("Triggers") + "\n"), after)
    csc = _crlf(banner("Custom Script Code"))
    first_csc = _find(o, csc, after)
    last_csc = o.rfind(csc, 0, t0)
    return (last_csc if last_csc != first_csc else t0), t0


def _splice_zone(o: str, texts: dict, calls: dict) -> str:
    """Replace the sections named in `texts` (title -> text or None) between the empty Custom Script Code section and
    the triggers, and the main calls named in `calls` (function -> present), keeping the editor's order."""
    first = _crlf(banner("Custom Script Code") + "\n")
    z0 = _find(o, first) + len(first)
    z1 = _trigger_start(o, z0 - len(first))[0]
    zone = o[z0:z1]
    starts = [m.start() for m in _BANNER_LINE.finditer(zone)]
    if zone[:starts[0] if starts else len(zone)].strip():
        raise ValueError("not an editor-generated war3map.j: unexpected text after the Custom Script Code banner")
    existing = {}
    for a, b in zip(starts, starts[1:] + [len(zone)]):
        title = _BANNER_LINE.match(zone, a).group(1)
        if title not in ZONE:
            raise ValueError(f"not an editor-generated war3map.j: unexpected section {title!r}")
        existing[title] = zone[a:b]
    parts = [(_crlf(texts[t]) if texts[t] else None) if t in texts else existing.get(t) for t in ZONE]
    o = o[:z0] + "".join(x for x in parts if x) + o[z1:]

    m0 = _find(o, "\r\nfunction main takes nothing returns nothing\r\n")
    m1 = _find(o, "\r\nendfunction\r\n", m0 + 2)
    lines = [x for x in o[m0:m1].split("\r\n") if not (x.startswith("    call ") and x[9:-4] in calls
                                                      and x.endswith("(  )"))]
    for k, fn in enumerate(MAIN_ORDER):
        if calls.get(fn):
            later = {f"    call {g}(  )" for g in MAIN_ORDER[k + 1:]}
            at = next((i for i, x in enumerate(lines) if x in later), len(lines))
            lines.insert(at, f"    call {fn}(  )")
    return o[:m0] + "\r\n".join(lines) + o[m1:]


def splice(original: str, tf, ct, td, world=None, placed=None, info=None, reference: str | None = None) -> str:
    """Regenerate globals (user-defined and gg_trg_ lines), InitGlobals, the header's Custom Script Code section and
    the Triggers section (sections, InitCustomTriggers, RunInitializationTriggers) of an editor-generated script.
    With a world.World also the Sound Assets, Regions and Cameras sections; with a placed.Placed the placed object,
    item table and random group sections; both with their main calls and globals. With a mapinfo.MapInfoParts also
    the file header and everything after the triggers (upgrades, tech tree, players, main, config). `reference`, an
    earlier script of the map, supplies sound lengths, object order and random item spelling (default: `original`)."""
    o = _crlf(original.replace("\r\n", "\n")) if "\r\n" not in original else original
    reference = o if reference is None else reference
    world_parts = worldgen.sections(world, reference) if world is not None else None
    placed_parts = placedgen.sections(placed, reference, tf, ct) if placed is not None else None
    texts, calls = {}, {}
    if world_parts is not None:
        for title, fn in WORLD_SECTIONS:
            texts[title] = banner(title) + "\n" + world_parts[fn] + "\n" if world_parts[fn] else None
            calls[fn] = bool(world_parts[fn])
    if placed_parts is not None:
        texts.update({t: placed_parts[t] for t in placedgen.TITLES})
        calls.update({fn: fn in placed_parts["main"] for fn in placedgen.MAIN_CALLS})
    if texts:
        o = _splice_zone(o, texts, calls)

    g0 = _find(o, "\r\nglobals\r\n") + len("\r\nglobals\r\n")
    g1 = _find(o, "\r\nendglobals\r\n", g0 - 2) + 2
    lines = o[g0:g1].split("\r\n")[:-1]
    rg = lines.index("    // Random Groups") if "    // Random Groups" in lines else len(lines)
    random_block = lines[rg:]
    head = lines[:rg - 1] if rg < len(lines) and rg and lines[rg - 1] == "" else lines[:rg]
    generated = head[head.index("    // Generated") + 1:] if "    // Generated" in head else []
    generated = [x for x in generated if not TRIGGER_DECL.fullmatch(x)]
    name_of = lambda x: (x.split() + ["", ""])[1]  # noqa: E731
    if world_parts is None:
        at = next((k for k, x in enumerate(generated) if not name_of(x).startswith(BEFORE_TRIGGERS)), len(generated))
    else:
        generated = [x for x in generated if not name_of(x).startswith(BEFORE_TRIGGERS)]
        decls = [declaration(jass_type, name, False, value) for jass_type, name, value in world_parts["globals"]]
        generated[0:0] = decls
        at = len(decls)
    triggers_decls = trigger_globals(tf)
    generated[at:at] = triggers_decls
    if placed_parts is not None:
        generated = [x for x in generated if not name_of(x).startswith(PLACED_DECL)]
        at += len(triggers_decls)
        generated[at:at] = [declaration(jass_type, name, False, "null") for jass_type, name in placed_parts["globals"]]
        count = placed_parts["random_groups"]
        random_block = ["    // Random Groups"] + [f"    integer array gg_rg_{k:03d}" for k in range(count)] if count else []
    globals_text = user_globals(tf, td) + ("    // Generated\n" + "".join(x + "\n" for x in generated) if generated else "")
    if random_block:
        globals_text += "\n" + "".join(x + "\n" for x in random_block)

    i0 = _find(o, "\r\nfunction InitGlobals takes nothing returns nothing\r\n", g1) + 2
    i1 = _find(o, "\r\nendfunction\r\n", i0) + len("\r\nendfunction\r\n")

    trig_banner = _crlf(banner("Triggers") + "\n")
    c0, t0 = _trigger_start(o, i1)

    ict = o.rfind(_crlf(f"{BAR}\nfunction InitCustomTriggers takes nothing returns nothing\n"))
    if ict < t0:
        raise ValueError("not an editor-generated war3map.j: InitCustomTriggers not found")
    end = _find(o, "\r\nendfunction\r\n\r\n", ict) + len("\r\nendfunction\r\n\r\n")
    rit = _crlf(f"{BAR}\nfunction RunInitializationTriggers takes nothing returns nothing\n")
    if o.startswith(rit, end):
        end = _find(o, "\r\nendfunction\r\n\r\n", end) + len("\r\nendfunction\r\n\r\n")
    triggers_text = trigger_sections(tf, ct, td) + init_custom_triggers(tf) + run_initialization_triggers(tf)

    head, rest = o[:g0], o[end:]
    if info is not None:
        m0 = _find(o, "\r\nfunction main takes nothing returns nothing\r\n")
        body = o[m0:_find(o, "\r\nendfunction\r\n", m0 + 2)] + "\r\n"
        present = {fn for fn in mapinfo.MAIN_CALLS if f"\r\n    call {fn}(  )\r\n" in body}
        parts = mapinfo.tail(info, present)
        rest = _crlf("".join(parts[t] for t in mapinfo.TITLES if parts[t]))
        if not o.startswith(_crlf(BAR + "\n")):
            raise ValueError("not an editor-generated war3map.j: no header comment")
        header_end = _find(o, _crlf("\n" + BAR + "\n\n"), 2) + len(_crlf("\n" + BAR + "\n\n"))
        head = _crlf(mapinfo.header(info)) + o[header_end:g0]
    return (head + _crlf(globals_text) + o[g1:i0] + _crlf(init_globals(tf, td)) + o[i1:c0]
            + _crlf(custom_script(ct)) + trig_banner + _crlf(triggers_text) + rest)


def new_script(tf, ct, td, world, placed, info, reference: str = "") -> str:
    """A whole editor-style war3map.j built from the map files alone (see splice for `reference`)."""
    skeleton = (BAR + "\n" + BAR + "\n\n" + banner("Global Variables") + "\nglobals\nendglobals\n\n"
                "function InitGlobals takes nothing returns nothing\nendfunction\n\n" + banner("Custom Script Code") + "\n"
                + banner("Triggers") + "\n" + f"{BAR}\nfunction InitCustomTriggers takes nothing returns nothing\nendfunction\n\n"
                + f"{BAR}\nfunction main takes nothing returns nothing\nendfunction\n\n")
    return splice(skeleton, tf, ct, td, world=world, placed=placed, info=info, reference=reference)
