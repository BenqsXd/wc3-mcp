"""The long form of the tool reference: every op shape, field list and pitfall, kept out of the tool descriptions so a
session does not pay for all of it before it has opened a map. wc3_help(topic) hands back the page for one tool; the
tool's own description keeps what a caller needs to decide whether to call it, and the op names to ask about.
"""

TOPICS: dict[str, str] = {}


def page(name: str, text: str) -> None:
    TOPICS[name] = text.strip("\n")


page("placed_edit", """
placed_edit(path, ops | ops_file, verbose=false) - all-or-nothing changes to placed units, items, start locations,
doodads and destructibles. Refs are "<kind>:<editor id>", angles degrees, positions world units.

PLACING ONE OBJECT
  {"op": "add", "kind": "unit"|"item"|"start_location"|"doodad"|"destructible", "type": "hfoo", "x": 0, "y": 0,
   ...fields}
  Editor defaults fill the rest: facing 270, z on the terrain, units owned by player 0, items neutral passive.
  A start location needs "owner" and no "type".

PLACING MANY
  {"op": "add", "kind": "destructible", <fields shared by every row>, "columns": ["type", "x", "y", "variation",
   "angle"], "rows": [["LTlt", -1833, -3653, 2, 113], ...]}
  {"op": "scatter", "kind", "types": {"LTlt": 3, "ATtr": 1} (weights) or ["LTlt"], "count", area, "exclude":
   [{"x", "y", "radius"} | {"rect": [l, b, r, t]}], "min_distance", "seed", "where": "land"|"water"|"any"}
  scatter is uniform random: use it to sprinkle, and the scenery ops below to build something that reads as placed.

CHANGING AND REMOVING
  {"op": "set", "ref": "unit:12", ...fields}          changes fields, "type" included
  {"op": "move", "ref": "start_location:0", "x", "y"} also moves the player's start in war3map.w3i (result: synced)
  {"op": "delete", "ref": "doodad:3"}                 refused while a trigger uses its gg_ name

FIELDS (the same names placed_list gives back)
  angle, scale (a number or [x, y, z]), variation, skin, owner, life (unit %, null for the default; destructible %),
  mana, gold, acquisition ("normal", "camp" or a range), hero {level, strength, agility, intelligence},
  inventory [{slot 0-5, item}], abilities [{id, autocast, level}], drops {table, sets: [[{item, chance}]]},
  random (uDNR/bDNR/iDNR: {level, item_class}, {group, position} or {units: [{type, chance}]}), color,
  waygate (a region name), and for doodads z and flags.

SCENERY OPS - seeded, deterministic, terrain-aware; each takes the placement fields of its kind plus "exclude",
"where" and "seed", and none of them stand objects on water, cliffs or the map boundary.
  {"op": "forest", "kind", "types", area ("rect", "x"/"y"/"radius", or "path" with "width"), "spacing" (the distance
   between trees at full density), "density" 0-1, "edge" (how far in from the border the wood thins),
   "clearings", "clearing_radius", "on_tiles": ["Lgrs"], "count"}
  {"op": "line", "kind", "types", "path", "spacing", "offset", "sides": "both"|"left"|"right"|"alternate"|"center",
   "face": "path"|"out"|"in"|<degrees>, "jitter"}
  {"op": "town", "kind", "types", "rect", "block": [w, h], "street", "margin", "spacing", "fill" 0-1,
   "props" (weights), "prop_spacing", "plaza": [l, b, r, t]}   - the result carries the streets for terrain_edit
  {"op": "cluster", "kind", "types", "x", "y", "radius", "count", "spacing", "falloff", "scale_range": [small, big]}
  {"op": "clear", area ("rect", circle or "path" with "width"), "kinds", "types"}
  A road is three ops: terrain_edit paint along the path, clear along it, then line for the lanterns.

RESULT
  created lists the new refs as ranges in op order ("doodad:422..909"); verbose=true lists every ref. Placing a
  doodad or destructible whose model the installed game cannot load, or whose scale is outside its type's own
  minimum and maximum, gives a warning. ops_file takes the ops array from a local JSON file instead.
  layout_check afterwards reports the spacing, the ground and what is still reachable.
""")

page("triggers_edit", """
triggers_edit(path, ops | ops_file, validate=false) - all-or-nothing Trigger Editor changes.

OPS
  {"op": "category", "name", "parent", "new_name"}
  {"op": "variable", "name", "type", "array_size", "initial", "category", "new_name"}
  {"op": "trigger", "name", "category", "description", "enabled", "initially_on", "run_on_init",
   "events"/"conditions"/"actions": [{"fn": "KillUnit", "args": [{"call": "GetTriggerUnit"}]}, ...]
   or "script": "<JASS or Lua>" or "script_file": "C:/local/trigger.j",
   "new_name", "index" or "after"}
  {"op": "delete", "what": "trigger"|"category"|"variable", "name"}
  {"op": "header", "script" | "script_file", "comment"}
  {"op": "script_replace", "name" (or "header": true), "old", "new"}   one exact piece, which must occur once

ARGUMENTS of a GUI function: a literal, {"preset": name}, {"var": name, "index"}, or {"call": name, "args": [...]}.
Block functions take "if"/"then"/"else" (IfThenElseMultiple), "conditions" (And/OrMultiple) or "actions" (loops).
GUI code is checked against TriggerData; data_search kind=trigger_function finds the functions and their arguments.

POSITION matters: the script emits trigger functions in tree order, so a trigger can only call what an earlier one
defines. Replacing a trigger keeps its place; "index" (0-based, inside its category) or "after" ("<trigger>", or null
for first) moves one on purpose. map_validate reports a call into a later trigger as function_order.

run_on_init is for script triggers; a GUI trigger runs at map start through the event {"fn": "MapInitializationEvent"}.
A "script" trigger gets the editor's InitTrig_<script name> wrapper when it does not define one, so the actions alone
are enough; the result says what was added.

validate=true regenerates the map script and checks it straight away (pjass, or the Lua syntax check) instead of
waiting for map_save; every error also carries script_line, its line inside the script that was sent.
The skill's references/triggers.md has the JASS pitfalls and the lint rules.
""")

page("terrain_edit", """
terrain_edit(path, ops | ops_file) - all-or-nothing terrain brushes. Every op is {"op": <brush>, <area>, <settings>}.

AREAS (world units): "x"/"y"/"radius" a circle, "rect": [left, bottom, right, top], "path": [[x, y], ...] with
"width" a stroke along a line, or no area at all for the whole map.

SHAPE
  {"op": "raise"|"lower", "amount", "falloff": "smooth"|"linear"|"flat"}
  {"op": "plateau", "height"}            flattens to that height, or to the centre corner's
  {"op": "smooth", "strength": 0-1}
  {"op": "noise", "amount", "seed", "falloff"}
  {"op": "cliff", "level": 0-15, "cliff": <cliff tile id>}
  {"op": "ramp"|"blight"|"boundary", "value": true|false}
  {"op": "water", "level": <surface z> | null}

GROUND
  {"op": "paint", "tile": "Lgrs"}        data_search kind=tile, tileset=<letter> finds ids; a map holds 16 tiles

The result reports the tile palette and what the ops added to it, and warns when a batch paints an unbuildable or
unwalkable tile over more than a few corners. Only a World Editor save recomputes pathing, shadows and minimap icons
from new terrain; until then terrain_get and terrain_render derive pathing from the tiles, cliffs, water and blight.
""")

page("terrain_landscape", """
The landscape brushes of terrain_edit, which shape ground the way the placed_edit scenery ops shape objects. They
take the same areas, and every one of them is deterministic for a given seed.

  {"op": "river", "path": [[x, y], ...], "width", "depth" (default 192), "bed": <tile>, "bank": <tile>,
   "water": true, "shallows": <extra width at a third of the depth>, "seed"}
      carves a bed that is deepest in the middle, fills it and paints the bed and the banks.

  {"op": "coast", area, "water_level" (default 0), "beach": <tile>, "shallow": <tile>, "slope" (default 256)}
      floods everything under the water level, slopes the sea floor away from the shore and paints the band above the
      waterline with the beach tile.

  {"op": "ridge", "path" with "width" or an area, "height", "roughness" 0-1, "seed", "cliff": true|<level>,
   "cliff_tile": <cliff tile id>}
      a raised spine with noise on it, optionally stepped into cliff levels.

  {"op": "erosion", area, "passes" (default 3), "strength" 0-1, "talus" (the slope it stops at, default 64)}
      thermal erosion: what is steeper than the talus slides downhill, so hills stop looking like cones.

  {"op": "terrace", area, "step" (height units per terrace), "strength" 0-1}
  {"op": "blend", area, "tiles": [a, b], "amount" 0-1, "seed"}    speckles the seam between two tiles the map holds
  {"op": "stamp", "from": [l, b, r, t], "to": [x, y], "rotate": 0|90|180|270, "mirror": "x"|"y",
   "layers": ["height","texture","cliff","water","flags"]}        copies a patch of terrain somewhere else

  {"op": "heightmap", "source": "C:/hills.png" | "content_base64", area, "amount" (world units between black and
   white), "base" (what black means), "mode": "set"|"add", "smooth", "channel": "luminance"|"red"|"green"|"blue"|
   "alpha"}
      reads a picture over the area. terrain_render heightmap="height" writes the same picture back out, and its
      result says which world units black and white stand for, so a round trip is exact.

SYMMETRY (the same op on terrain_edit and placed_edit)
  {"op": "mirror", "axis": "x"|"y"|"point"|"rot90"|"rot180"|"rot270", "from": [l, b, r, t] (default: the half or
   quadrant the axis implies), "centre": [x, y] (default: the middle of the playable area),
   "layers": [...] (terrain), "kinds": [...] (placed), "owner_map": {"0": 1} (placed: the owner the copies get),
   "replace": true (placed: clear the target area first)}
      Build one half or quadrant properly, then mirror it: a reflection flips every facing, a rotation turns it.
      rot90 and rot270 need a square source area.
""")

page("game_test", """
game_test(path, timeout, results, close, screenshot, probe, probe_seconds, probe_script, probe_script_file,
          probe_functions, wait, screenshots, screenshot_every) - run a map in the game and collect what it reports.

HOW A RUN ENDS
  The map script writes a result file with PreloadGenClear / PreloadGenStart / Preload("text") /
  PreloadGenEnd("folder\\\\file.txt"); list those files in results, relative to CustomMapData under
  Documents\\Warcraft III, and the run ends as soon as all of them exist. Without results it runs the full timeout.

PROBES (a throwaway copy of the map, so the map itself never gets test triggers)
  probe=true                 reports units, heroes, gold and lumber per playing slot at probe_seconds, plus the text
                             the map shows (probe.messages)
  probe_script / _file       statements in the map's language that run at that moment; they may call the map's own
                             functions, read its udg_ globals and wait with TriggerSleepAction
  probe_functions            whole functions of your own, emitted before the probe code (callbacks for your triggers)
  In the probe code:
    ProbeReport(text)                          -> probe.reports, any length
    ProbeExpect(name, condition)               -> probe.checks, checks_failed, checks_passed
    ProbeCountEvent(EVENT_..., "name")         counts a player-unit event from then on
    ProbeEventCount("name")                    reads the count
    ProbeCamera(x, y, distance, seconds)       looks at a place and waits there, for the screenshot series

BACKGROUND AND PICTURES
  wait=false starts the run and returns at once; game_status then reports it under run, and its whole result under
  run.result when it ends. A second run while one is going is refused (run_active); game_close ends it.
  screenshot=true saves one PNG at the end; screenshots=N with screenshot_every seconds saves a series while the map
  runs, which is how scenery gets looked at in the game.

PITFALLS
  A Battle.net login screen ends the run after about 30 s with login_required and leaves the game open: once the user
  has logged in there, the same call continues in that game (continued_game). Every other launch can ask again, so put
  many checks into one run. An open dialog pauses a single-player game, so report before it opens. The game keeps
  about 259 characters of one Preload string (truncated lists the lines that hit it). A loading screen that waits for
  a key gets a space press (loading_screen_keys).
""")

page("data_search", """
data_search(kind, query, limit, offset, locale, balance, hd, tileset) - find ids and paths in the game data.

KINDS
  objects      unit, item, ability, buff, upgrade, destructible, doodad - searched by id, name or editor suffix
  terrain      tile, cliff, water, weather - tile results carry buildable, walkable and flyable
  sound        sound
  files        model, icon, file - by path substring or glob; a glob without a layer prefix matches in any layer
               ("PathTextures/8x8*"). One result per file: ref is the path as object data and scripts write it
               (backslashes, icons .blp, models .mdl), layers the storage layers holding it, id a storage path
  GUI          trigger_function, trigger_type, trigger_preset - the World Editor's own function and type tables
  script       native - the installed build's common.j, Blizzard.j and common.ai: natives, functions, constants and
               handle types with their signatures; globs work ("Blz*Frame*")

tileset ("L" or "Lordaeron Summer") scopes tile, cliff, doodad and destructible to one tileset; a plain query is a
text search, not a tileset filter. Doodad and destructible results carry model_ok: false when the installed game
cannot load the model in HD or in classic graphics (the editor's), with variations_ok listing the ones that do load.
balance picks the gameplay data set: Custom_V1 (current), Custom_V0, Melee_V0, or null for the base files.
""")

page("map_save", """
map_save(path, dest, format, force, rebuild_script, validate, merge_external) - save the working copy.

By default it backs up the original and replaces it atomically; dest/format write a copy elsewhere (an mpq archive or
a map folder). rebuild_script: "auto" regenerates war3map.j / war3map.lua when triggers, regions, cameras, sounds,
placed objects or map info changed, "always" whenever possible, "never" leaves the script alone. The minimap
war3mapMap.blp is added when missing and redrawn after terrain edits unless the map imports its own.
validate runs map_validate first, compiles a regenerated or edited script and refuses to save on errors of either.

When the original changed on disk since it was opened (a World Editor save), the save refuses with source_changed
unless merge_external=true, which takes every file this working copy has not changed from the map on disk - the
pathing, shadows and minimap the editor recomputed - and keeps the working copy's own changes; force=true instead
overwrites the map with the working copy. The editor holds the file open while it shows the map, so the round trip is
edits here -> editor_map close -> map_save -> editor_map open -> editor_map save.
""")

page("map_validate", """
map_validate(path) - cross-file checks of an open map. Errors break the map; warnings are defects shipped maps carry.

ERRORS
  script_language   war3map.w3i selects a script the map does not have
  gui / variable / trigger_ref / variable_ref / custom_text / trigger_name / structure   trigger data against
                    TriggerData, the map's variables and the generated script
  generated_ref     a gg_ name the current script does not define
  trigstr           a TRIGSTR the string table does not hold
  object / objdata  an object whose base id or field does not exist
  function_order    a trigger calling a function a later trigger defines, which does not compile
  format            a file this codec cannot parse

WARNINGS
  derived_files     terrain newer than the pathing, shadow and minimap files only the World Editor recomputes
  model             a placed object whose model is in neither the game data nor the imports
  start_location    the marker and war3map.w3i disagree about a player's start
  import            an entry of war3map.imp the map does not hold
  command_card      two buttons of one unit on the same position (unless its stock base has the same clash)
  inherited_builds  a copied unit with its own uabi that kept its base's build list
  locked_ability    an ability whose required research nothing in the map offers
  order_string      an order a unit will refuse, or one where the ability data and the editor disagree
  ability_order     two abilities of one unit sharing an order string
  reachable         start locations cut off from each other, or a preplaced unit its own player cannot walk to
""")

page("terrain_get", """
terrain_get(path, area, layers, step) - terrain corners of an open map, one every 128 units, as grids of rows running
south to north inside area [left, bottom, right, top] (default the whole map), every step-th corner.

LAYERS
  height        the ground height without cliffs (ground z = height + (cliff_level - 2) * 128)
  texture       the tile id
  cliff_level   0-15
  water         the water surface z, or null where the ground is dry
  flags         letters: r ramp, b blight, w water, x boundary
  pathing       letters: w unwalkable, f unflyable, b unbuildable, B blight

pathing comes from the editor's last save (war3map.wpm), or, after terrain_edit and before the next editor save, is
derived from the current tiles, cliffs, water and blight without object footprints; pathing_source says which.
An area narrower than the corner spacing uses the nearest corner line and says so in window.snapped. The result also
carries the tile palette and the map bounds. At most 65536 corners per call.
""")

page("asset_edit", """
asset_edit(source, dest, ops, format, compression, quality, mipmaps) - edit a texture or a model and write the result.
source and dest are as in asset_convert: {"file": "C:/local/x.blp"}, {"map": "war3mapImported/x.blp", "path": <open
map>} or {"game": "War3.w3mod:...."} for a source. ops apply in order.

TEXTURE OPS
  {"op": "resize", "width", "height"}
  {"op": "crop", "left", "top", "right", "bottom"}
  {"op": "grayscale"}
  {"op": "brightness", "factor"}
  {"op": "tint", "color": [r, g, b], "strength"}
  {"op": "overlay", "source", "x", "y", "width", "height", "opacity"}
  {"op": "icon", "kind": "BTN"|"DISBTN"|"PASBTN"|"DISPASBTN"}    the game's 64x64 command button styles

MODEL OPS
  {"op": "retexture", "texture": <index or the current path>, "path": <new path>, "replaceable_id"}
  {"op": "scale", "factor"}                geometry, pivots, extents, translations, emitters, cameras, collision
  {"op": "rename_sequence", "sequence": <index or name>, "name"}
  {"op": "remove_sequence", "sequence"}
  {"op": "team_color", "material": <index>}    a layer under a classic material, texture slot 4 of a Reforged one
  {"op": "add_attachment", "name", "parent", "position": [x, y, z], "path"}
""")

page("campaign_edit", """
campaign_edit(path, ops) - all-or-nothing changes to an open campaign (.w3n), applied to the campaign_get document.

  {"op": "set", "path": "name", "value": "My Campaign"}
  {"op": "set", "path": "minimap", "value": {"preset": "Human"} | {"map": "Ch1.w3x"} |
   {"file": "war3campImported/map.tga"} | null}
  {"op": "set", "path": "loading_screen.background", "value": {"preset": "Orc" or an index} |
   {"file": "war3campImported/intro.webm"} | null}                 ambient_sound works the same way
  loading_screen.cursor, background_version and fog ({"style": "linear", "z_start", "z_end", "density",
   "color": {r, g, b, a}} or null)
  {"op": "append", "path": "buttons", "value": {"chapter", "title", "map", "visible", "cinematic"}}
  {"op": "set" | "remove", "path": "buttons[0]..."}

MAPS INSIDE THE CAMPAIGN
  {"op": "add_map", "source": "C:/maps/Ch1.w3x", "name"}
  {"op": "replace_map", "name", "source"}
  {"op": "remove_map", "name"}
  {"op": "extract_map", "name", "dest"}     edit it with map_open, put it back with replace_map
""")

page("ui_edit", """
ui_edit(path, file, statements | text, toc) - write a custom UI layout (.fdf) into an open map.

statements is the shape ui_get gives back:
  [{"key": "IncludeFile", "args": ["UI\\\\FrameDef\\\\UI\\\\EscMenuTemplates.fdf"]},
   {"block": "Frame", "args": ["BACKDROP", "MyPanel", "INHERITS", "EscMenuBackdropTemplate"], "statements": [
      {"key": "Width", "args": [0.2]},
      {"key": "Height", "args": [0.12]},
      {"key": "SetPoint", "args": ["TOPLEFT", "ConsoleUI", "TOPLEFT", 0.01, -0.01]},
      {"block": "Frame", "args": ["TEXT", "MyPanelTitle"], "statements": [
         {"key": "SetPoint", "args": ["TOP", "MyPanel", "TOP", 0.0, -0.008]},
         {"key": "Text", "args": ["SCORE"]}]}]}]
Anchors are TOPLEFT, TOP, TOPRIGHT, LEFT, CENTER, RIGHT, BOTTOMLEFT, BOTTOM, BOTTOMRIGHT. Coordinates are fractions
of the screen (0.8 wide, 0.6 tall in the game's own frame space).

The file is imported under war3mapImported and listed in a .toc beside it; the result carries the frames it defines,
the problems a check found (unknown frame type, an anchor that is not a corner, a SetPoint to a frame the file never
defines, a texture the map does not hold) and the script that loads it: BlzLoadTOCFile, then BlzCreateFrame or
BlzGetFrameByName. ui_get reads a file back, the game's own UI included.
""")


def help_text(topic: str | None = None) -> dict:
    """One reference page, or the list of them."""
    if topic is None or topic not in TOPICS:
        return {"topics": sorted(TOPICS),
                **({"unknown_topic": topic} if topic else {}),
                "note": "wc3_help(topic) gives the full op shapes and field lists of that tool"}
    return {"topic": topic, "text": TOPICS[topic]}
