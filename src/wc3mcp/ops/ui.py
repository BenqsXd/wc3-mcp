"""Custom user interface: the .fdf layout files a map imports, the .toc that lists them, and the script that loads
them (BlzLoadTOCFile) and reaches the frames by name (BlzGetFrameByName). ui_get reads and checks, ui_edit writes.
"""
import base64

from ..errors import ToolError
from ..formats import fdf
from .imports import imports_edit
from .strings import file_prefix

IMPORT_FOLDER = "war3mapImported"
# frame types the game knows; SIMPLE* frames are the ones a map may create at runtime with BlzCreateSimpleFrame
FRAME_TYPES = frozenset("""
BACKDROP BUTTON CHATDISPLAY CHECKBOX CONTROL DIALOG EDITBOX FRAME GLUEBUTTON GLUECHECKBOX GLUEEDITBOX GLUEPOPUPMENU
GLUETEXTBUTTON HIGHLIGHT LISTBOX MENU MODEL POPUPMENU SCROLLBAR SIMPLEBUTTON SIMPLECHECKBOX SIMPLEFRAME
SIMPLESTATUSBAR SLASHCHATBOX SLIDER SPRITE TEXT TEXTAREA TEXTBUTTON TIMERTEXT
""".split())
ANCHORS = frozenset(("TOPLEFT", "TOP", "TOPRIGHT", "LEFT", "CENTER", "RIGHT", "BOTTOMLEFT", "BOTTOM", "BOTTOMRIGHT"))
# statements whose first argument names a texture or model file
TEXTURE_KEYS = ("BackdropBackground", "BackdropEdgeFile", "File", "Texture", "HighlightAlphaFile",
                "ButtonPushedTexture", "ControlPushedBackdrop")
LOADER = """// call this once at map start, then keep the frames you need
call BlzLoadTOCFile("{toc}")
set udg_Panel = BlzCreateFrame("{first}", BlzGetOriginFrame(ORIGIN_FRAME_GAME_UI, 0), 0, 0)
"""


def _names(project) -> dict[str, str]:
    return {f["name"].lower(): f["name"] for f in project.list_files()}


def _read(project, name: str) -> bytes | None:
    real = _names(project).get(name.replace("/", "\\").lower())
    return project.read(real) if real else None


def _catalog_file(catalog, path: str) -> bytes | None:
    full = catalog.storage.resolve(path.replace("\\", "/"), **catalog.layer)
    return catalog.storage.read(full) if full else None


def ui_get(project, catalog, path: str | None = None) -> dict:
    """Without path: the map's own .fdf and .toc files. With one: that file parsed, its frames and what a check of
    it found. A path the map does not hold is looked up in the game data, so the stock UI can be read too."""
    files = [f["name"] for f in project.list_files() if f["name"].lower().endswith((".fdf", ".toc"))]
    if path is None:
        return {"files": sorted(files), "note": "ui_get path=<file> parses one; the game's own UI is readable too "
                                                "(data_search kind=file query=*.fdf)"}
    data = _read(project, path)
    source = "map"
    if data is None:
        data = _catalog_file(catalog, path)
        source = "game data"
    if data is None:
        raise ToolError("not_found", f"no UI file {path!r} in the map or the game data",
                        hint="ui_get without a path lists the map's files; data_search kind=file finds the game's")
    if path.lower().endswith(".toc"):
        listed = [line.strip() for line in data.decode("utf-8", "replace").splitlines() if line.strip()]
        return {"path": path, "source": source, "kind": "toc", "files": listed}
    tree = fdf.parse(data)
    frames = [{"type": t, "name": n, "parent": parent,
               "inherits": next((str(a) for a in node["args"][2:] if a not in ("INHERITS", "WITHCHILDREN")), None),
               "statements": len(node["statements"])}
              for t, n, node, parent in fdf.frames(tree)]
    return {"path": path, "source": source, "kind": "fdf", "includes": fdf.includes(tree), "frames": frames,
            "statements": tree, "problems": check(tree, project, catalog)}


def check(tree: list[dict], project=None, catalog=None) -> list[dict]:
    """Layout mistakes that cost a game launch: an unknown frame type, an anchor that is not a corner, a SetPoint to
    a frame the file does not define, a texture neither the map nor the game data holds."""
    out, defined = [], set()
    for frame_type, name, _node, _parent in fdf.frames(tree):
        defined.add(name)
        if frame_type.upper() not in FRAME_TYPES:
            out.append({"frame": name, "problem": f"frame type {frame_type!r} is not one the game knows",
                        "hint": "one of: " + ", ".join(sorted(FRAME_TYPES))})
    names = _names(project) if project is not None else {}
    for frame_type, name, node, _parent in fdf.frames(tree):
        for statement in node["statements"]:
            key, args = statement.get("key"), statement.get("args", [])
            if key in ("SetPoint", "Anchor"):
                for arg in args:
                    if isinstance(arg, str) and arg.isupper() and arg not in ANCHORS and not arg.isdigit():
                        out.append({"frame": name, "problem": f"{arg!r} is not an anchor point",
                                    "hint": "one of: " + ", ".join(sorted(ANCHORS))})
                target = next((str(a) for a in args if isinstance(a, str) and not a.isupper()), None)
                if target and target not in defined and target not in ("ConsoleUI", "ConsoleUIBackdrop"):
                    out.append({"frame": name, "problem": f"SetPoint refers to {target!r}, which this file does not "
                                                          "define", "hint": "the frame must exist before it is used"})
            elif key in TEXTURE_KEYS and args and isinstance(args[0], str) and "\\" in args[0]:
                ref = args[0]
                found = ref.replace("/", "\\").lower() in names or f"{IMPORT_FOLDER}\\{ref}".lower() in names
                if not found and catalog is not None:
                    stem = ref.rsplit(".", 1)[0]
                    found = any(catalog.storage.resolve(stem.replace("\\", "/") + ext, **catalog.layer)
                                for ext in (".blp", ".dds", ".tga", ".mdx", ".mdl", ""))
                if not found:
                    out.append({"frame": name, "problem": f"{key} {ref!r} is in neither the map's imports nor the "
                                                          "game data", "hint": "imports_edit adds a file to the map"})
    return out


def ui_edit(project, catalog, path: str, statements: list | None = None, text: str | None = None,
            toc: str | None = None) -> dict:
    """Write an .fdf into the map (from statements, the ui_get shape, or from text) and list it in a .toc, so
    BlzLoadTOCFile can load it. Returns the problems a check found and the script that loads the file."""
    if (statements is None) == (text is None):
        raise ToolError("bad_value", "give either statements (the ui_get shape) or text (an .fdf file)",
                        path="statements")
    if not path.lower().endswith(".fdf"):
        raise ToolError("bad_value", f"{path!r} is not an .fdf file", path="path")
    if statements is not None:
        if not isinstance(statements, list):
            raise ToolError("bad_value", "statements is a list of {key, args} and {block, args, statements}",
                            path="statements")
        text = fdf.serialize(statements)
    try:
        tree = fdf.parse(text)
    except Exception as e:   # noqa: BLE001 - the codec raises FormatError, but a bad shape can raise anything
        raise ToolError("bad_value", f"this is not valid FDF text: {e}", path="text") from e
    name = path if path.lower().startswith(IMPORT_FOLDER.lower()) else f"{IMPORT_FOLDER}\\{path}"
    toc_name = toc or (name.rsplit(".", 1)[0] + ".toc")
    if not toc_name.lower().startswith(IMPORT_FOLDER.lower()):
        toc_name = f"{IMPORT_FOLDER}\\{toc_name}"
    listed = []
    existing = _read(project, toc_name)
    if existing is not None:
        listed = [line.strip() for line in existing.decode("utf-8", "replace").splitlines() if line.strip()]
    entry = name.split("\\", 1)[1] if name.lower().startswith(IMPORT_FOLDER.lower()) else name
    if entry not in listed:
        listed.append(entry)
    ops = [{"op": "add", "path": name.replace("\\", "/"), "content_base64": _b64(text)},
           {"op": "add", "path": toc_name.replace("\\", "/"), "content_base64": _b64("\n".join(listed) + "\n")}]
    imports_edit(project, ops)
    frames = [n for _t, n, _node, _parent in fdf.frames(tree)]
    loader = LOADER.format(toc=toc_name.replace("\\", "\\\\"), first=frames[0] if frames else "MyFrame")
    return {"path": name, "toc": toc_name, "frames": frames, "problems": check(tree, project, catalog),
            "script": loader, "map_prefix": file_prefix(project),
            "note": "the map must load the toc once at map start (the script above), and BlzGetFrameByName(name, 0) "
                    "reaches a frame the file defines"}


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")
