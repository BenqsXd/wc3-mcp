"""Imported files: war3map.imp entries kept in step with the files inside the map."""
import base64
from pathlib import Path

from ..errors import ToolError
from ..formats import imp
from ..formats.binary import FormatError
from ..project.workspace import check_name
from .strings import file_prefix


def _key(path: str) -> str:
    return path.replace("\\", "/").lower()


def _load(project) -> imp.ImportList:
    try:
        return imp.parse(project.read(file_prefix(project) + ".imp"))
    except ToolError as e:
        if e.code == "no_such_file":
            return imp.ImportList()
        raise
    except FormatError as e:
        raise ToolError("bad_file", f"{file_prefix(project)}.imp: {e}") from e


def _content(op: dict) -> bytes:
    if "source" in op:
        src = Path(str(op["source"]))
        if not src.is_file():
            raise ToolError("not_found", f"source file not found: {src}")
        return src.read_bytes()
    if "content_base64" in op:
        try:
            return base64.b64decode(op["content_base64"], validate=True)
        except (ValueError, TypeError) as e:
            raise ToolError("bad_content", f"content_base64 is not valid base64: {e}") from e
    raise ToolError("bad_op", "add needs source (a local file path) or content_base64")


def imports_list(project) -> list[dict]:
    sizes = {_key(f["name"]): f["size"] for f in project.list_files()}
    return [{"path": e.path, "flag": e.flag, "size": sizes.get(_key(e.path))} for e in _load(project).entries]


def imports_edit(project, ops: list) -> dict:
    imports = _load(project)
    existing = {_key(f["name"]) for f in project.list_files()}
    writes: dict[str, tuple[str, bytes]] = {}  # lower-case key -> (name as given, data)
    deletes: set[str] = set()
    for i, op in enumerate(ops):
        try:
            if not isinstance(op, dict) or not isinstance(op.get("path"), str):
                raise ToolError("bad_op", "each op needs an op name and a path string",
                                hint='{"op": "add", "path": "war3mapImported/icon.blp", "source": "C:/icon.blp"}')
            name = check_name(op["path"])
            key = _key(name)
            entry = next((e for e in imports.entries if _key(e.path) == key), None)
            if op.get("op") == "add":
                data = _content(op)
                if entry is None:
                    imports.entries.append(imp.ImportEntry(imp.DEFAULT_FLAG, name.replace("\\", "/")))
                writes[key] = (name, data)
                deletes.discard(key)
            elif op.get("op") == "remove":
                if entry is None and key not in existing and key not in writes:
                    raise ToolError("no_such_import", f"{op['path']} is neither imported nor in the map")
                if entry is not None:
                    imports.entries.remove(entry)
                writes.pop(key, None)
                deletes.add(key)
            else:
                raise ToolError("bad_op", f"unknown op {op.get('op')!r}", hint="use add or remove")
        except ToolError as e:
            e.details.setdefault("op_index", i)
            raise
    for name, data in writes.values():
        project.write(name, data)
    for f in project.list_files():
        if _key(f["name"]) in deletes:
            project.delete(f["name"])
    if ops:
        project.write(file_prefix(project) + ".imp", imp.serialize(imports))
    return {"imports": imports_list(project)}
