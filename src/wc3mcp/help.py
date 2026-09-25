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
  {"op": "delete", "ref": "doodad:3", "missing_ok": true}   skipped (result skipped) when the ref is gone
  {"op": "delete", "kind": "doodad", "area": [l, b, r, t], "types": ["LTlt"]}   everything of a kind in an area
                                                      (types optional); result deleted: n. Run twice, it deletes 0

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
  {"op": "cluster", "kind", "types", "x", "y", "radius", "count", "spacing" (default 128; the rim spreads to
   spacing x (1 + 2 x falloff)), "falloff", "scale_range": [small, big]}   - warns when it places fewer than count
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
terrain_edit(path, ops | ops_file, quiet) - all-or-nothing terrain brushes. Every op is {"op": <brush>, <area>,
<settings>}. The landscape brushes (river, coast, ridge, erosion, terrace, blend, stamp, heightmap) and mirror are
on wc3_help("terrain_landscape").

AREAS (world units): "x"/"y"/"radius" a circle, "rect": [left, bottom, right, top], "path": [[x, y], ...] with
"width" a stroke along a line, or no area at all for the whole map.

SHAPE
  {"op": "raise"|"lower", "amount", "falloff": "smooth"|"linear"|"flat"}
  {"op": "plateau", "height"}            flattens to that height, or to the centre corner's
  {"op": "smooth", "strength": 0-1}
  {"op": "noise", "amount", "seed", "falloff"}
  {"op": "cliff", "level": 0-15, "cliff": <cliff tile id>}
                                         neighbouring corners stay within 2 levels: the op's own corners keep theirs,
                                         the ground around them steps (result: cliffs)
  {"op": "ramp"|"blight"|"boundary", "value": true|false}
  {"op": "water", "level": <surface z> | null}
                                         level is an absolute z (a level-3 mesa's ground is at 128 + height); it is
                                         stored in quarter units, so -40 reads back as -40.1. Corners whose ground is
                                         above the level stay dry. The result's water list gives the stored level, the
                                         depth range and deep_corners per water op

GROUND
  {"op": "paint", "tile": "Lgrs"}        data_search kind=tile, tileset=<letter> finds ids; a map holds 16 tiles

The result reports the tile palette and what the ops added to it, and warns when a batch paints an unbuildable or
unwalkable tile over more than a few corners (quiet=["tile_pathing"] drops those on a map where nothing is built,
quiet=["derived_files"] the stale-files reminder). Only a World Editor save recomputes pathing, shadows and minimap
icons from new terrain; until then terrain_get and terrain_render derive pathing from the tiles, cliffs, water and
blight.

WATER DEPTH
  Water up to about 52 deep is wadeable (walkable, unbuildable); deeper than about 53 stops ground units (the editor's
  own pathing flips between 52 and 56; flat water 47.9 deep read walkable and 63.9 unwalkable after an editor save).
  Outland water stops them at any depth. Each tileset draws its water at its own offset below the stored level
  (Ashenvale and Underground 76.8, Dungeon 96, Outland 192, the rest 89.6); level always means the drawn surface.
""")

page("terrain_landscape", """
The landscape brushes of terrain_edit, which shape ground the way the placed_edit scenery ops shape objects. They
take the same areas, and every one of them is deterministic for a given seed. The basic brushes (raise, lower,
plateau, smooth, noise, paint, cliff, water) are on wc3_help("terrain_edit").

  {"op": "river", "path": [[x, y], ...], "width", "depth" (default 192), "bed": <tile>, "bank": <tile>,
   "water": true, "shallows": <extra width at a third of the depth>, "water_level": <surface z>,
   "walkable": true|false, "seed"}
      carves a bed that is deepest in the middle, fills it and paints the bed and the banks. The surface is
      water_level when given; else the level of water already in the river's way (a branch started inside another
      river or a lake joins it at that level; the result says joined); else a quarter of depth below the lowest ground
      it crosses. walkable=false keeps a channel at least 69 deep along the middle (a barrier), walkable=true keeps all
      of it at most 40 deep (a ford). The result's water entry gives the level and the depth range it made.

  {"op": "coast", area, "water_level" (default 0), "beach": <tile>, "shallow": <tile>, "slope" (default 256)}
      floods everything whose ground (cliff level included) lies under the water level (a surface z), slopes the sea floor away from the shore and paints the band above the
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
  {"op": "mirror", "axis": "x"|"y"|"point"|"rot90"|"rot180"|"rot270"|"rot4", "from": [l, b, r, t] (default: the half or
   quadrant the axis implies), "centre": [x, y] (default: the middle of the playable area),
   "layers": [...] (terrain), "kinds": [...] (placed), "owner_map": {"0": 1} (placed: the owner the copies get),
   "replace": true (placed: clear the target area first)}
      Build one half or quadrant properly, then mirror it: a reflection flips every facing, a rotation turns it.
      rot90, rot270 and rot4 need a square source area. rot4 fills the other three quadrants from one (three
      quarter turns of the same source). A source whose image overlaps it is refused. x reflects the x coordinate
      (a left-right mirror), y the y coordinate.
""")

page("game_test", """
game_test(path, timeout, results, close, screenshot, probe, probe_seconds, probe_script, probe_script_file,
          probe_functions, wait, screenshots, screenshot_every, login, login_wait) - run a map in the game and
          collect what it reports.

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
  probe_init                 statements run inside map initialization, before the map's own initialization triggers
                             and before any timer: set what a dialog would have asked for, or call
                             ProbeSkipDialogs() so DialogDisplay/DialogDisplayBJ show nothing (a shown dialog pauses a
                             single-player game, and the probe queued behind it never runs; the report then says
                             dialog=suppressed)
  In the probe code:
    ProbeReport(text)                          -> probe.reports, any length
    ProbeExpect(name, condition)               -> probe.checks, checks_failed, checks_passed
    ProbeCountEvent(EVENT_..., "name")         counts a player-unit event from then on
    ProbeEventCount("name")                    reads the count
    ProbeCamera(x, y, distance, seconds)       looks at a place and waits there, for the screenshot series
    ProbeHandleCount()                         the handle id of a fresh location: sample it around a loop to count
                                               what the loop leaks
  Every probe reports handles (start at 0 s, end at the report, growth and per_minute): a few dozen over a run is
  normal; a steady climb of one per missile or per tick is a leak (pool dummy units instead of CreateUnit/RemoveUnit:
  118 handles over 120 missiles fell to 2 over 60). The report is written at the end, so PreloadGenClear in probe
  code no longer loses ProbeReport lines.

BACKGROUND AND PICTURES
  wait=false starts the run and returns at once; game_status then reports it under run, and its whole result under
  run.result when it ends. A second run while one is going is refused (run_active); game_close ends it.
  screenshot=true saves one PNG at the end; screenshots=N with screenshot_every seconds saves a series that starts
  the moment the map runs (a probe writes a start marker; map_started_after says when), which is how scenery gets
  looked at in the game. A frame that could not be taken is listed in screenshots_failed with the reason. The run
  ends when its results are written, so put ProbeCamera stops before the last ProbeReport.

  In probes: GroupEnumUnitsInRect (and the other GroupEnum calls) skip units hidden with ShowUnit(false) - keep their
  handles, or read placed_list. Raw codes are base-256 integers, so 'n020' + 10 is 'n02:', not 'n02A'.

FOCUS
  The game only loads while its window is in front. focus.raised counts how often the run raised it and
  focus.lost_to names the windows that held the foreground meanwhile. The Battle.net app's windows are minimised once
  the game window exists (launcher_minimized). stuck_at="loading_screen": the map loaded (the log has "Opening map")
  but the key that leaves the loading screen never reached the game.

LOGIN
  A game started directly ("Warcraft III.exe -launch -loadfile ...") has no Battle.net session and shows the login
  panel; "Keep me logged in" there lasts about an hour, and signing the Battle.net app in does not help a direct
  launch. The app starts the game as "-launch -uid w3" and hands it its own session, so a run started through the
  app never meets the panel.
  login="auto" (default) and "battlenet" therefore start the game through the app: the map is copied to the server's
  own launch folder, that path is stored in the app's launch options for Warcraft III (Battle.net.config,
  Games.w3.AdditionalLaunchArguments), and the app is asked to launch W3. The app reads those options when it
  starts, so the first run that stores them restarts the app (login.battlenet.restarted; any options that were there
  are kept in battlenet-previous-launch-arguments.txt in the server's folder). Later runs need no restart, because
  the stored path never changes. launched_by says which route a run took.
  The user has to be logged in to the Battle.net app once, with "Keep me logged in". If the app is logged out the
  game shows the panel anyway: then the game window flashes with a warning sound and the run waits login_wait
  seconds (default 120) for the user, and reports login_required if nobody signs in.
  "wait" and "stop" start the game directly: "wait" flashes the window and waits, "stop" ends after 30 s.
  Time at a login screen does not count against timeout (login_seconds says how much there was). A run left at
  login_required keeps the game open, and the same call again continues in it (continued_game).
  A game that reaches its main menu instead of the map is started again once (relaunched: ["stuck_at_main_menu"]);
  twice gives stuck_at: "main_menu".
  The tools never type, read or store credentials.
  Every run puts the app's launch options back when it ends - on its result files, a timeout, a kill or an error -
  and deletes the launch copy, so a Play in the Battle.net app starts Warcraft III the way it did before (the result
  says so under launcher). That stops and restarts the app when it is running, because the app rewrites its config
  from memory. Only a game left open (close=false, login_required) keeps them until game_close; game_status reports
  under launcher what a Play would start today.

PITFALLS
  Every launch can meet a login screen (see LOGIN), so put many checks into one run. An open dialog pauses a single-player game, so report before it opens. The game keeps
  about 259 characters of one Preload string (truncated lists the lines that hit it). A loading screen that waits for
  a key gets a space press (loading_screen_keys).
  Nothing in a probe stands in for a player's click on a shop: IssueNeutralImmediateOrderById returned false for
  heroes a Tavern did sell, and ForceUIKey does nothing on a neutral shop's card. A shop sells only to a unit standing
  close to it (Tavern 300-350, Goblin Merchant 250) and not in the first seconds of a map. When the question is "can
  a player buy this", balance_report kind="shop" and map_validate cover what the data can say; the rest is a person
  at the keyboard. A probe that sets the map up for itself (skipping a pick phase) never tests the path a player
  takes: keep one probe that only waits and checks that nothing happened early.
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
               handle types with their signatures; globs work ("Blz*Frame*"). observed says what a game run saw a
               native do where that differs from its name (SetUnitAcquireRange 0 is ignored, 1 reads 200, ...)
  orders       order - every order string: targets (immediate/unit/point, from the editor's presets), the abilities
               whose order fields name it, backed (a shipped ability uses it), resolves (true: OrderId() knew it in a
               sweep of every string; false: OrderId() returned 0 - a Channel on it can never be cast), order_id, and
               disagree when the ability data and the editor differ. Not every listed string is in the game's order
               table (32 of 347, some used by shipped abilities): pick resolves true for a Channel's Ncl6, one no other ability of the
               map uses, whose targets match its Ncl2.

A query with * ? or [ is a glob over the id, name and editor suffix for every kind ("*" lists them all, paged: sound
labels for an ability's aefs, for instance); without them it is a substring. data_get kind=model or icon takes a path
the way object data writes it (Units\\NightElf\\X\\X.mdl, a .blp icon) and answers with the .mdx or .dds the game loads.

tileset ("L" or "Lordaeron Summer") scopes tile, cliff, doodad and destructible to one tileset; a plain query is a
text search, not a tileset filter. Doodad and destructible results carry model_ok: false when the installed game
cannot load the model in HD or in classic graphics (the editor's), with variations_ok listing the ones that do load,
and also pathing (the texture) and blocks (whether it stops walking).
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
  learn_card        two hero abilities (uhab) of one hero on the same learn-menu cell or hotkey (arpx/arpy, arhk)
  inherited_builds  a copied unit with its own uabi that kept its base's build list
  locked_ability    an ability whose required research nothing in the map offers
  order_string      an order a unit will refuse, or one where the ability data and the editor disagree
  ability_order     two abilities of one unit sharing an order string
  reachable         start locations cut off from each other, or a preplaced unit its own player cannot walk to
  hero_id_case      a copy of a hero whose id starts lowercase (the game makes it an ordinary unit)
  hero_ability_slots  more than 5 abilities in a hero's uhab
  hero_skill_points a hero with fewer ability ranks than MaxHeroLevel (points it can never spend)
  channel_target    a no-target Channel copy (Ncl2 0) whose Ncl6 order needs a target, so the cast does nothing
  channel_order     a Channel copy whose Ncl6 is a string OrderId() does not know in the game (never castable)
  channel_levels    a Channel copy whose Ncl3 (Options) lacks the visible bit at some ranks and not others: no button
                    at those ranks (Channel's own Ncl3 is 0 at every level, so set every rank)
  waygate_self      a waygate leading into the region it stands in
  shop_stock        a shop sells an item whose isto (Stock Maximum) is 0: it is never in stock, the shop greys it
  shop_hotkey       entries of one shop card on the same hotkey (a copied item keeps its base's uhot)
  icon              an iico, aart, arar, uico or ussi the game does not have and the map does not import (a blank
                    green square in the game)
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
  pathing       letters: w unwalkable, f unflyable, b unbuildable, B blight (water deeper than about 53: w)

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
The .toc lists every layout by its archive path (war3mapImported\\score.fdf) and ends with blank lines: the game
reads entries as paths, and a bare file name loads nothing, so every BlzCreateFrame of its templates returns null.
ui_get on a .toc reports entries that are neither in the map nor in the game data. A StringList in a map's .fdf
loaded with BlzLoadTOCFile replaces the game's own strings of the same keys (the STR/AGI/INT tooltips come from
UI\\FrameDef\\InfoPanelStrings.fdf, BONUS_HITPOINTS and friends; keep their %d). BlzFrameClick(button) fires
FRAMEEVENT_CONTROL_CLICK, which is how a probe presses a button; hover and mouse state cannot be faked from a probe.
""")


page("strings_edit", """
strings_edit(path, ops) - all-or-nothing edits to the map's string table (war3map.wts).

  {"op": "set", "id": 3, "text": "Guard Tower"}          changes one entry, or creates it with that id
  {"op": "add", "text": "New quest"}                     answers with the id it got ("id" forces one)
  {"op": "remove", "id": 7}
  {"op": "replace", "find": "Guard", "with": "Sentry", "regex": false, "ids": [3, 4]}
      goes through every entry (or only the ids given): one name changed everywhere the map shows it
  {"op": "import", "entries": {"3": "Wachturm", "4": "Wache"}}     a translated table in one go

strings_get(path, query, limit, offset, used_by) reads them back; used_by lists the files that point at each entry
and marks the ones nothing refers to any more. Object data, map info and GUI triggers hold TRIGSTR references into
this table, so they follow a change, but the map script keeps its own copy of trigger text: map_save or script_build
regenerates it.
""")

page("script_recipe", """
script_recipe(name, params, path, trigger, install) - tested JASS systems as triggers_edit ops.

  damage_detection   one function every damage event passes through            (no parameters)
  unit_indexer       a number on every unit, plus a hashtable for its data     (no parameters)
  respawn            units of one owner come back where they died              delay, owner
  waves              timed waves from a spawn to a target, growing each round  spawn, target, types, interval,
                                                                              count, growth, owner
  scoreboard         a multiboard with a row per player                        title, column
  hero_tavern        a tavern that sells heroes and places the bought one      heroes, at, tavern
  quest              an entry in the quest log                                 title, description, icon, required
  camera             the camera every player starts with                       distance, angle, rotation
  cinematic          camera shots with spoken lines and their waits            shots, lines, letterbox, start_after

  cinematic shots: [{"at": [x, y], "seconds": 4, "distance", "angle", "rotation", "pan_to": [x, y], "pan_seconds"}]
  cinematic lines: [{"name": "Arthas", "text": "...", "seconds": 4, "unit": "Hamg"}] - line i belongs to shot i

Without a name it lists them. The ops come back for triggers_edit so they can be edited first; install=true (with a
path) puts them in, rebuilds the script and checks it with pjass. Each recipe names the trigger after itself unless
"trigger" says otherwise, puts it in a "Systems" category, and declares its state as GUI variables.
""")

page("balance_report", """
balance_report(path, kind, ids, compare, balance) - what the map's own objects are worth, from their fields.

  kind="unit"     damage per second per enabled attack ((base + dice * (sides + 1) / 2) / cooldown), effective life
                  (life / (1 - 0.06 * armour / (1 + 0.06 * armour))), gold, lumber, food, speed, sight, build time,
                  and damage per gold, life per gold and a combined worth per 100 gold
  kind="item"     the bonuses its abilities give (Iagi, Iint, Istr, Iatt, Ilif, Iman, Idef, ...) and per 100 gold
  kind="ability"  the per-level curve: cooldown, mana, range, duration, area, damage, damage per mana, damage per
                  second of cooldown. It also lists button_cells: abilities sharing a command-card cell, which clash
                  on a unit that is given both at runtime - over every id, also past the 50 reported rows
  kind="shop"     each shop's card (ids: the shops; default the map's units with usei/useu): per entry the gold and
                  lumber, the stock fields, hotkey, cell, a sold unit's race and requirement, and problems (Stock
                  Maximum 0, a hotkey shared on the card). A shop sells only to a buyer's unit standing close to it
                  (Tavern 300-350, Goblin Merchant 250, measured) and not in the first seconds of a map

A unit whose udty is "hero" also gets a hero block: its attributes at level 1 and at MaxHeroLevel, and the life,
mana, armour, attack damage bonus and damage per second they make of the unit's fields through the gameplay
constants (constants_get). Those numbers replace the plain ones in the row, because every hero's own fields say life
100, mana 0 and damage 2, and the row is compared with the stock heroes instead of the stock units.

ids defaults to what the map created or modified (objdata_list). compare=true adds the stock objects closest in price
and food, and flags a ratio far outside theirs. The result carries the formulas and the fields it read, so a number
can be checked instead of believed.
""")

page("constants_edit", """
constants_get(path, keys, modified_only) and constants_edit(path, set, reset) - gameplay constants, the World
Editor's Gameplay Constants. The game reads Units/MiscGame.txt and Units/MiscData.txt; a map overrides single keys
in war3mapMisc.txt, which an editor save keeps as it is.

  constants_get()                       every constant with its value, the game's default, whether the map changes it
                                        and the file it comes from; modified_only=true just the map's own
  constants_edit(set={"MaxHeroLevel": 25, "MaxUnitLevel": 25, "HeroAbilityLevelSkip": 1})
  constants_edit(reset=["MaxHeroLevel"])   back to the game's own value; the last key removes war3mapMisc.txt

A misspelt key is refused (the game would ignore it silently; map_validate warns with check "constant" for one a
file written by hand carries), and so is text where the game keeps a number, because the game would read 0.

WORTH KNOWING
  MaxHeroLevel 10, MaxUnitLevel 20            the level caps; a hero needs 3 x 7 + 4 = 25 ability ranks to spend a
                                              point at every level of a 25 cap
  HeroAbilityLevelSkip 2                      hero levels between ability ranks, unless the ability sets alsk
  NeedHeroXP 200, NeedHeroXPFormulaA/B/C      the experience curve (200, 500, 900, 1400, 2000, ... by default)
  HeroFactorXP 80,70,60,50,0                  the creep experience a hero still gets from level 5 on
  StrHitPointBonus 25, IntManaBonus 15        what an attribute point is worth: life and mana come from these, not
  StrAttackBonus 1, AgiDefenseBonus 0.30      from uhpm/umpm (balance_report kind="unit" computes it for a hero)
  AgiAttackSpeedBonus 0.02, AgiDefenseBase -2
  HeroMaxReviveCostGold/Time, ReviveLevelFactor   what reviving a hero costs
""")

page("map_flow", """
map_flow(path, area, origins, targets) and melee_check(path, sample) - how a map plays, in walking distances.

map_flow, per start location: the distance to its own gold mine and to the nearest expansion (and where that is), the
walkable corners within 1500 units (room for a base), and how much ground it reaches. Per pair of starts: the walking
distance between them, the narrowest choke on the way and where that choke is. Then the walkable corners of the map,
how many of them the starts reach, and the pockets they do not - on a melee map mostly creep camps ringed by trees,
which open when the trees come down. A choke under about 400 world units is a one-unit pass, 400-900 a lane, above
1500 open ground. Water deeper than about 53 blocks, like a cliff.

ORIGINS AND TARGETS (the 32-unit cells the game paths on)
  map_flow(path, origins=[...], targets=[...]) with [x, y] points, region names or "start:N": can a ground unit walk
  from any origin to each target? A place on a building, a mine or a tree counts from the ground around it; an origin
  with no walkable ground within 768 units is refused. Per target: reachable, distance, gap (the narrowest free width across the shortest
  walk) and gap_at; the sampled route only with verbose=true. min_gap=N keeps only the unreachable targets and those
  narrower than N (hidden counts the rest), fields keeps only those keys per target. sealed=true when no target is reachable - the proof that a tree wall,
  a moat or a cliff ring is closed; a leak comes back with the hole it goes through. Terrain comes from war3map.wpm when
  the editor saved it after the last terrain and doodad edit, else it is derived (tiles, cliffs, water depth, boundary, the area
  outside the playable area); every placed object's pathing texture is added, turned with the object in quarter turns.
  A gap of one cell (32) lets small units through; units with a collision size above 16 need wider.
  Before the first editor save the terrain part is derived, and the result carries a warning saying so. layout_check's
  narrowest gives the tightest gap between the starts; a gap under about 128 stops heroes (collision above 16), 64 or
  96 is a wall for them.

melee_check measures the same map the way the melee maps shipped with this install are measured - mines per player,
start distance, distance to a player's own mine, creep camps, playable area per player, tile count, doodad and unit
density - and reports each metric with the shipped maps' p10, median and p90 for the same player count and a verdict
(inside, below, above). The norms are mined from those maps once per install and cached; sample caps how many are read
the first time.
""")

def help_text(topic: str | None = None) -> dict:
    """One reference page, or the list of them."""
    if topic is None or topic not in TOPICS:
        return {"topics": sorted(TOPICS),
                **({"unknown_topic": topic} if topic else {}),
                "note": "wc3_help(topic) gives the full op shapes and field lists of that tool"}
    return {"topic": topic, "text": TOPICS[topic]}
