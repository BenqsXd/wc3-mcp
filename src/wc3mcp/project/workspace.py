"""Map working copies: unpack, edit files, save with backup + atomic replace, snapshots."""
import hashlib
import json
import os
import shutil
import time
from pathlib import Path, PureWindowsPath

from .. import config, pathguard
from ..errors import ToolError
from ..mpq.reader import HASH_EMPTY, Archive, MpqError
from ..mpq.writer import SPECIAL, RawEntry, capture_unnamed, write_archive

BACKUPS_KEPT = 20
_IGNORED = {n.upper() for n in SPECIAL + ("(signature)",)}
_RAW_FIELDS = ("hash_index", "name_a", "name_b", "locale", "platform", "fsize", "flags", "src_pos", "key")


def project_id(source) -> str:
    return hashlib.sha1(os.path.normcase(os.path.abspath(source)).encode("utf-8")).hexdigest()[:12]


def fingerprint(path: Path) -> dict:
    if path.is_dir():
        h, size = hashlib.sha256(), 0
        for f in sorted(p for p in path.rglob("*") if p.is_file()):
            data = f.read_bytes()
            h.update(f.relative_to(path).as_posix().lower().encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
            size += len(data)
        return {"size": size, "sha256": h.hexdigest()}
    if not path.is_file():
        return {"missing": True}
    data = path.read_bytes()
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def check_name(name: str) -> str:
    n = name.replace("/", "\\")
    if (not n or n.startswith("\\") or ":" in n or n.upper() in _IGNORED
            or any(part in ("", ".", "..") for part in n.split("\\"))):
        raise ToolError("bad_name", f"invalid map file name: {name!r}",
                        hint="use a relative name such as war3mapImported\\icon.blp")
    return n


class MapProject:
    def __init__(self, source: Path, work: Path, manifest: dict):
        self.source, self.work, self.m = source, work, manifest

    # opening
    @classmethod
    def open(cls, source) -> "MapProject":
        source = Path(source).resolve()
        if not source.exists():
            raise ToolError("not_found", f"map not found: {source}")
        work = config.home() / "work" / project_id(source)
        manifest = work / "manifest.json"
        if manifest.is_file():
            p = cls(source, work, json.loads(manifest.read_text("utf-8")))
            if not p.source_changed():
                return p  # resume, keeping unsaved edits
            if p.m["dirty"] or p.m["deleted"]:
                raise ToolError("stale_work", "the map changed on disk while the working copy has unsaved edits",
                                hint="map_close with discard=true, then map_open again")
            shutil.rmtree(work)
        return cls._extract(source, work)

    @classmethod
    def _extract(cls, source: Path, work: Path) -> "MapProject":
        (work / "files").mkdir(parents=True)
        m = {"source": str(source), "fingerprint": fingerprint(source), "files": {}, "dirty": [], "deleted": [],
             "unnamed": [], "protected": False, "problems": []}
        p = cls(source, work, m)
        if source.is_dir():
            m.update(format="folder", sector_size=4096, hash_size=None, reserved_slots=[])
            for f in sorted(x for x in source.rglob("*") if x.is_file()):
                p._put(str(PureWindowsPath(f.relative_to(source))), f.read_bytes())
        else:
            try:
                arc = Archive.open(source)
                names = arc.list()
                unnamed = arc.unnamed_entries(names)
                m.update(format="mpq", sector_size=arc.sector_size, hash_size=len(arc.hashes),
                         reserved_slots=[e.index for e in arc.hashes if e.block != HASH_EMPTY],
                         protected=not arc.listfile_names() or bool(unnamed))
                (work / "prefix.bin").write_bytes(arc.prefix)
                for name in names:
                    if name.upper() not in _IGNORED:
                        p._put(name, arc.read(name))
                (work / "unnamed").mkdir()
                for i, entry in enumerate(unnamed):
                    raw = capture_unnamed(arc, entry)
                    (work / "unnamed" / f"{i}.bin").write_bytes(raw.data)
                    m["unnamed"].append({k: getattr(raw, k) for k in _RAW_FIELDS})
                m["problems"] = arc.problems
            except MpqError as e:
                shutil.rmtree(work, ignore_errors=True)
                raise ToolError("bad_archive", f"cannot read map: {e}") from e
        p._flush()
        return p

    # files
    def _put(self, name: str, data: bytes) -> None:
        entry = self.m["files"].get(name.upper())
        if entry is None:
            try:
                rel = check_name(name).replace("\\", "/")
            except ToolError:  # hostile names from protected maps stay addressable but never touch real paths
                rel = "_unsafe/" + hashlib.sha1(name.encode("utf-8", "surrogatepass")).hexdigest()
            entry = self.m["files"][name.upper()] = {"name": name, "path": rel}
        target = self.work / "files" / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def _entry(self, name: str) -> dict:
        entry = self.m["files"].get(name.replace("/", "\\").upper())
        if entry is None:
            raise ToolError("no_such_file", f"{name} is not in the map", hint="map_status lists the files")
        return entry

    def _mark(self, name: str, dirty: bool) -> None:
        key = name.upper()
        self.m["dirty"] = [n for n in self.m["dirty"] if n.upper() != key]
        self.m["deleted"] = [n for n in self.m["deleted"] if n.upper() != key]
        (self.m["dirty"] if dirty else self.m["deleted"]).append(name)
        self._flush()

    def _flush(self) -> None:
        (self.work / "manifest.json").write_text(json.dumps(self.m, indent=1), "utf-8")

    def source_changed(self) -> bool:
        return fingerprint(self.source).get("sha256") != self.m["fingerprint"].get("sha256")

    def list_files(self) -> list[dict]:
        files = [{"name": e["name"], "size": (self.work / "files" / e["path"]).stat().st_size}
                 for e in self.m["files"].values()]
        return sorted(files, key=lambda f: f["name"].lower())

    def read(self, name: str) -> bytes:
        return (self.work / "files" / self._entry(name)["path"]).read_bytes()

    def write(self, name: str, data: bytes) -> None:
        name = check_name(name)
        self._put(name, data)
        self._mark(self.m["files"][name.upper()]["name"], dirty=True)

    def delete(self, name: str) -> None:
        entry = self._entry(name)
        del self.m["files"][entry["name"].upper()]
        (self.work / "files" / entry["path"]).unlink()
        self._mark(entry["name"], dirty=False)

    def status(self) -> dict:
        return {"source": str(self.source), "format": self.m["format"], "protected": self.m["protected"],
                "file_count": len(self.m["files"]), "dirty": sorted(self.m["dirty"]),
                "deleted": sorted(self.m["deleted"]), "unnamed_files": len(self.m["unnamed"]),
                "source_changed": self.source_changed(), "problems": self.m["problems"]}

    # saving
    def save(self, dest=None, format: str | None = None, force: bool = False) -> dict:
        dest = Path(dest).resolve() if dest else self.source
        fmt = format or self.m["format"]
        in_place = dest == self.source
        if fmt not in ("mpq", "folder"):
            raise ToolError("bad_format", f"unknown format {fmt!r}", hint="use 'mpq' or 'folder'")
        if in_place and fmt != self.m["format"]:
            raise ToolError("format_change_in_place", "changing the format needs a different destination",
                            hint="pass dest")
        if fmt == "folder" and self.m["unnamed"]:
            raise ToolError("unnamed_files", "this map has files with unknown names that a folder cannot hold",
                            hint="save with format='mpq'")
        if in_place and not force and self.source_changed():
            raise ToolError("source_changed", "the map was modified outside this working copy since it was opened",
                            hint="map_close(discard=true) and reopen to pick up those changes, or force=true to overwrite them")
        if in_place and not (self.m["dirty"] or self.m["deleted"]) and not force:
            return {"saved": False, "reason": "no changes", "path": str(dest)}
        pathguard.ensure_writable(dest)
        files = {e["name"]: (self.work / "files" / e["path"]).read_bytes() for e in self.m["files"].values()}
        backup = self._backup(dest)
        if fmt == "mpq":
            self._write_mpq(dest, files)
        else:
            self._write_folder(dest, files)
        if in_place:
            self.m["fingerprint"] = fingerprint(dest)
            self.m["dirty"], self.m["deleted"] = [], []
            self._flush()
        return {"saved": True, "path": str(dest), "format": fmt, "backup": backup}

    def _write_mpq(self, dest: Path, files: dict[str, bytes]) -> None:
        preserved = tuple(RawEntry(data=(self.work / "unnamed" / f"{i}.bin").read_bytes(), **u)
                          for i, u in enumerate(self.m["unnamed"]))
        prefix = self.work / "prefix.bin"
        kwargs = {"prefix": prefix.read_bytes() if prefix.is_file() else b"", "sector_size": self.m["sector_size"]}
        if preserved:
            kwargs.update(preserved=preserved, hash_size=self.m["hash_size"],
                          reserved_slots=frozenset(self.m["reserved_slots"]))
        try:
            data = write_archive(files, **kwargs)
        except MpqError as e:
            raise ToolError("write_failed", str(e)) from e
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".wc3mcp-tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)

    def _write_folder(self, dest: Path, files: dict[str, bytes]) -> None:
        tmp = dest.with_name(dest.name + ".wc3mcp-tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        for name, data in files.items():
            target = tmp / check_name(name).replace("\\", "/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        old = dest.with_name(dest.name + ".wc3mcp-old")
        if dest.exists():
            os.replace(dest, old)
        os.replace(tmp, dest)
        if old.is_dir():
            shutil.rmtree(old)
        elif old.exists():
            old.unlink()

    def _backup(self, dest: Path) -> str | None:
        if not dest.exists():
            return None
        folder = config.home() / "backups" / f"{dest.stem}-{project_id(dest)}"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000:06d}{dest.suffix}")
        if dest.is_dir():
            shutil.copytree(dest, target)
        else:
            shutil.copy2(dest, target)
        for old in sorted(folder.iterdir())[:-BACKUPS_KEPT]:
            shutil.rmtree(old) if old.is_dir() else old.unlink()
        return str(target)

    # snapshots
    def snapshot(self, action: str, label: str | None = None) -> dict:
        root = config.home() / "snapshots" / self.work.name
        if action == "list":
            return {"snapshots": sorted(p.name for p in root.iterdir()) if root.is_dir() else []}
        if not label or not all(c.isalnum() or c in "-_." for c in label) or label in (".", ".."):
            raise ToolError("bad_label", "snapshot labels use letters, digits, '-', '_' and '.'")
        snap = root / label
        if action == "create":
            shutil.rmtree(snap, ignore_errors=True)
            shutil.copytree(self.work, snap)
            return {"created": label}
        if action not in ("restore", "diff"):
            raise ToolError("bad_action", f"unknown snapshot action {action!r}", hint="create, restore, list or diff")
        if not snap.is_dir():
            raise ToolError("no_such_snapshot", f"snapshot {label!r} does not exist", hint="map_snapshot action=list")
        snap_files = json.loads((snap / "manifest.json").read_text("utf-8"))["files"]
        if action == "diff":
            cur = self.m["files"]

            def digest(base: Path, e: dict) -> str:
                return hashlib.sha256((base / "files" / e["path"]).read_bytes()).hexdigest()

            return {"added": sorted(cur[k]["name"] for k in cur.keys() - snap_files.keys()),
                    "removed": sorted(snap_files[k]["name"] for k in snap_files.keys() - cur.keys()),
                    "changed": sorted(cur[k]["name"] for k in cur.keys() & snap_files.keys()
                                      if digest(self.work, cur[k]) != digest(snap, snap_files[k]))}
        shutil.rmtree(self.work / "files")
        shutil.copytree(snap / "files", self.work / "files")
        self.m["files"] = snap_files
        self.m["dirty"], self.m["deleted"] = sorted(e["name"] for e in snap_files.values()), []
        self._flush()
        return {"restored": label}

    def close(self, discard: bool = False) -> dict:
        if (self.m["dirty"] or self.m["deleted"]) and not discard:
            raise ToolError("unsaved_changes", "the working copy has unsaved edits",
                            hint="map_save first, or map_close with discard=true",
                            dirty=self.m["dirty"], deleted=self.m["deleted"])
        shutil.rmtree(self.work, ignore_errors=True)
        return {"closed": str(self.source)}
