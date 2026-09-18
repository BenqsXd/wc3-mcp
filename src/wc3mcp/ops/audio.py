"""Sound and music, end to end: the file goes into the map, the entry goes into war3map.w3s with the settings that
kind of sound needs, and the script that plays it comes back. Doing it by hand is three tools and a table of defaults
nobody remembers.
"""
import base64
from pathlib import Path

from ..errors import ToolError
from .elements import SOUND_EXTENSIONS, elements_edit, elements_list
from .imports import imports_edit

IMPORT_FOLDER = "war3mapImported"
# what each kind of sound needs; the numbers are the World Editor's own defaults for that role
KINDS = {
    "sound": {"volume": 127, "pitch": 1.0, "channel": 0, "is_3d": False, "looping": False,
              "stop_when_out_of_range": False, "music": False, "eax": "DefaultEAXON"},
    "sound3d": {"volume": 127, "pitch": 1.0, "channel": 0, "is_3d": True, "looping": False,
                "stop_when_out_of_range": True, "music": False, "eax": "DefaultEAXON",
                "min_distance": 600.0, "max_distance": 8000.0, "distance_cutoff": 3000.0,
                "cone_inside": 0.0, "cone_outside": 0.0, "cone_outside_volume": 127},
    "ambient": {"volume": 90, "pitch": 1.0, "channel": 3, "is_3d": True, "looping": True,
                "stop_when_out_of_range": True, "music": False, "eax": "DefaultEAXON",
                "min_distance": 600.0, "max_distance": 6000.0, "distance_cutoff": 3000.0},
    "music": {"volume": 127, "pitch": 1.0, "channel": 0, "is_3d": False, "looping": True,
              "stop_when_out_of_range": False, "music": True, "eax": "DefaultEAXON"},
}
SCRIPT = {
    "sound": 'call PlaySoundBJ(gg_snd_{name})',
    "sound3d": 'call PlaySoundAtPointBJ(gg_snd_{name}, 100, Location(0, 0), 0)   '
               '// or AttachSoundToUnit(gg_snd_{name}, u)',
    "ambient": 'call PlaySoundBJ(gg_snd_{name})   // a looping 3D sound: attach it to a unit or a point',
    "music": 'call PlayMusic("{path}")   // music plays by file path, not through the sound handle',
}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def sound_add(project, catalog, name: str, source: str | None = None, game_path: str | None = None,
              kind: str = "sound", label: str | None = None, settings: dict | None = None) -> dict:
    """Import a sound (or point at one the game already has), register it as `name` in war3map.w3s with the defaults
    that kind needs, and answer with the script that plays it. `label` is one of the game's own sound labels
    (data_search kind=sound), which is how the editor inherits a stock sound's settings - not free text."""
    if kind not in KINDS:
        raise ToolError("bad_value", f"kind {kind!r} is not one of: " + ", ".join(KINDS), path="kind")
    if (source is None) == (game_path is None):
        raise ToolError("bad_value", 'give either source (a local audio file) or game_path (one of the game\'s own '
                                     'sounds, from data_search kind=sound or kind=file)', path="source")
    if not name or not name.replace("_", "").isalnum():
        raise ToolError("bad_value", "name: letters, digits and _ (it becomes gg_snd_<name> in the script)",
                        path="name")
    if source is not None:
        local = Path(source)
        if local.suffix.lower() not in SOUND_EXTENSIONS:
            raise ToolError("bad_value", f"{local.suffix or source!r} is not an audio file the game reads; it takes "
                                         + ", ".join(SOUND_EXTENSIONS), path="source")
        try:
            data = local.read_bytes()
        except OSError as e:
            raise ToolError("not_found", f"cannot read {source}: {e}", path="source") from e
        path = f"{IMPORT_FOLDER}\\{local.name}"
        imports_edit(project, [{"op": "add", "path": path.replace(chr(92), "/"), "content_base64": _b64(data)}])
        imported = len(data)
    else:
        path, imported = game_path.replace("/", "\\"), 0
    fields = dict(KINDS[kind])
    for key, value in (settings or {}).items():
        if key not in fields and key not in ("fade_in", "fade_out", "priority", "pitch_variance", "dialogue",
                                             "cone_orientation"):
            raise ToolError("bad_value", f"settings.{key} is not a sound field",
                            hint="elements_list kind=sound shows them all", path=f"settings.{key}")
        fields[key] = value
    elements_edit(project, catalog, "sound", [{"op": "upsert", "name": name, "path": path,
                                               "label": label or "", **fields}])
    entry = next((s for s in elements_list(project, "sound")["items"] if s["name"] in (name, f"gg_snd_{name}")), None)
    return {"name": name, "variable": f"gg_snd_{name}", "path": path, "kind": kind,
            "imported_bytes": imported, "sound": entry,
            "script": SCRIPT[kind].format(name=name, path=path.replace(chr(92), chr(92) * 2)),
            "note": ("the map script needs regenerating before the handle exists: map_save or script_build does it. "
                     "A 3D sound is heard where it is played, so attach it to a unit or a point")}
