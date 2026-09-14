"""Local (installed) CASC storage reader. Layouts follow CascLib (CascIndexFiles.cpp, CascReadFile.cpp,
CascRootFile_TVFS.cpp) and wowdev.wiki TACT; verified against Warcraft III 3.0.0.24268.

Paths are returned as stored: '/' between folders, ':' when entering a nested VFS
(e.g. "War3.w3mod:_HD.w3mod:Units/Human/Footman/Footman.mdx"). Lookup is case-insensitive; '\\' == '/'."""
from __future__ import annotations  # Storage.list() would shadow builtin list in later annotations

import bisect
import fnmatch
import os
import re
import struct

from .blte import blte_decode

ENTRY_HEADER = 30  # before "BLTE" in data.###: reversed EKey (16), u32 size, u16 flags, 2x u32 checksums


def _config(path) -> dict[str, list[str]]:
    d = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.split()
    return d


class Storage:
    def __init__(self, root):
        self.root = os.fspath(root)
        self.data_dir = os.path.join(self.root, "Data", "data")
        self.build = _config(self._config_path(self._active_build_key()))
        self._buckets: dict[int, dict[bytes, tuple[int, int, int]]] = {}
        self._files = {}
        self._encoding = None
        self._names = None
        self.root_info: dict[str, list[str]] = {}
        self.vfs_dirs: set[str] = set()
        self.blte_stats: dict[str, int] = {}

    @property
    def build_name(self) -> str:
        return self.build.get("build-name", ["unknown"])[0]

    def _active_build_key(self) -> str:
        with open(os.path.join(self.root, ".build.info"), encoding="utf-8") as f:
            rows = [line.rstrip("\r\n").split("|") for line in f if line.strip()]
        cols = [c.split("!")[0] for c in rows[0]]
        records = [dict(zip(cols, r)) for r in rows[1:]]
        return next((r for r in records if r.get("Active") == "1"), records[0])["Build Key"]

    def _config_path(self, key: str) -> str:
        return os.path.join(self.root, "Data", "config", key[:2], key[2:4], key)

    # local index (.idx v7)
    @staticmethod
    def bucket_of(ekey: bytes) -> int:
        x = 0
        for b in ekey[:9]:
            x ^= b
        return (x & 0xF) ^ (x >> 4)

    def _bucket(self, b: int) -> dict[bytes, tuple[int, int, int]]:
        if b in self._buckets:
            return self._buckets[b]
        best = max((f for f in os.listdir(self.data_dir) if re.fullmatch("%02x[0-9a-f]{8}\\.idx" % b, f)),
                   key=lambda f: int(f[2:10], 16))
        with open(os.path.join(self.data_dir, best), "rb") as f:
            data = f.read()
        rev, bucket, _flags, size_bytes, offset_bytes, key_bytes, seg_bits, _max = struct.unpack_from("<HBBBBBBQ", data, 8)
        if (rev, bucket, size_bytes, offset_bytes, key_bytes) != (7, b, 4, 5, 9):
            raise ValueError(f"unsupported index file {best}")
        entries_size = struct.unpack_from("<I", data, 0x20)[0]
        d, mask, width = {}, (1 << seg_bits) - 1, key_bytes + offset_bytes + size_bytes
        for p in range(0x28, 0x28 + entries_size - entries_size % width, width):
            k = data[p:p + 9]
            packed = int.from_bytes(data[p + 9:p + 14], "big")
            size = int.from_bytes(data[p + 14:p + 18], "little")
            if k not in d or d[k][2] <= ENTRY_HEADER:  # prefer a real entry over a header-only placeholder
                d[k] = (packed >> seg_bits, packed & mask, size)
        self._buckets[b] = d
        return d

    def locate(self, ekey: bytes):
        return self._bucket(self.bucket_of(ekey)).get(bytes(ekey[:9]))

    def read_ekey(self, ekey: bytes) -> bytes | None:
        loc = self.locate(ekey)
        if loc is None or loc[2] <= ENTRY_HEADER:
            return None
        archive, offset, size = loc
        f = self._files.get(archive)
        if f is None:
            f = self._files[archive] = open(os.path.join(self.data_dir, "data.%03d" % archive), "rb")
        f.seek(offset)
        return blte_decode(f.read(size)[ENTRY_HEADER:], self.blte_stats)

    # encoding (CKey -> EKey)
    def ckey_to_ekey(self, ckey: bytes) -> bytes | None:
        if self._encoding is None:
            e = self._encoding = self.read_ekey(bytes.fromhex(self.build["encoding"][1]))
            if e[:2] != b"EN" or e[2] != 1:
                raise ValueError("unsupported encoding file")
            self._ckey_len, self._ekey_len = e[3], e[4]
            self._page_size = int.from_bytes(e[5:7], "big") * 1024
            self._page_count = int.from_bytes(e[9:13], "big")
            self._pages_at = 22 + int.from_bytes(e[18:22], "big")
            step = self._ckey_len + 16  # first key + page MD5
            self._first_keys = [e[self._pages_at + i * step:self._pages_at + i * step + self._ckey_len]
                                for i in range(self._page_count)]
        e, ckey = self._encoding, bytes(ckey)
        i = bisect.bisect_right(self._first_keys, ckey) - 1
        if i < 0:
            return None
        p = self._pages_at + self._page_count * (self._ckey_len + 16) + i * self._page_size
        end = p + self._page_size
        while p + 6 + self._ckey_len <= end:
            key_count = e[p]  # u8 key count, u40be content size, ckey, ekey * key_count
            if key_count == 0:
                break
            if e[p + 6:p + 6 + self._ckey_len] == ckey:
                return e[p + 6 + self._ckey_len:p + 6 + self._ckey_len + self._ekey_len]
            p += 6 + self._ckey_len + self._ekey_len * key_count
        return None

    def read_ckey(self, ckey: bytes) -> bytes | None:
        ekey = self.ckey_to_ekey(ckey)
        return None if ekey is None else self.read_ekey(ekey)

    # names (TVFS manifest + legacy text root for original casing)
    def _load_names(self) -> None:
        vfs_ekeys = {bytes.fromhex(v[1])[:9] for k, v in self.build.items() if re.fullmatch(r"vfs-(root|\d+)", k)}
        self._names = {}
        self._parse_tvfs(self.read_ekey(bytes.fromhex(self.build["vfs-root"][1])), "", vfs_ekeys)
        text = self.read_ckey(bytes.fromhex(self.build["root"][0]))  # "War3.w3mod:Units/UnitData.slk|<ckey>|..."
        for line in (text or b"").decode("utf-8", "replace").splitlines():
            parts = line.split("|")
            if len(parts) >= 2:
                k = self.norm(parts[0])
                self.root_info[k] = parts
                if k in self._names:
                    self._names[k] = (parts[0], self._names[k][1])

    def _parse_tvfs(self, data: bytes, prefix: str, vfs_ekeys: set[bytes]) -> None:
        if data[:4] != b"TVFS" or data[4] != 1:
            raise ValueError("not TVFS v1")
        ekey_size = data[6]
        path_off, path_size, vfs_off, _vfs_size, cft_off, cft_size = struct.unpack_from(">6I", data, 12)
        cft_width = 4 if cft_size > 0xFFFFFF else 3 if cft_size > 0xFFFF else 2 if cft_size > 0xFF else 1

        def spans_at(val):
            p = vfs_off + val
            n = data[p]
            p += 1
            if not 1 <= n <= 224:
                return None
            out = []
            for _ in range(n):
                _file_off, span_size = struct.unpack_from(">II", data, p)
                c = cft_off + int.from_bytes(data[p + 8:p + 8 + cft_width], "big")
                out.append((bytes(data[c:c + ekey_size]), span_size))
                p += 8 + cft_width
            return out

        # Path table is a prefix tree: [0x00 sep before] [u8 len + name] [0x00 sep after] [0xFF + u32be value];
        # value & 0x80000000 -> folder (low 31 bits = folder byte length incl. value), else VFS table offset.
        def walk(p, end, base):
            cur = base
            while p < end:
                if data[p] == 0:
                    cur += "/"
                    p += 1
                if p < end and data[p] != 0xFF:
                    n = data[p]
                    cur += data[p + 1:p + 1 + n].decode("utf-8", "replace")
                    p += 1 + n
                post = False
                if p < end and data[p] == 0:
                    post = True
                    p += 1
                if p < end and data[p] != 0xFF:
                    post = True
                if post:
                    cur += "/"
                if p < end and data[p] == 0xFF:
                    val = int.from_bytes(data[p + 1:p + 5], "big")
                    p += 5
                    if val & 0x80000000:
                        folder_end = p + (val & 0x7FFFFFFF) - 4
                        walk(p, folder_end, cur)
                        p = folder_end
                    else:
                        spans = spans_at(val)
                        if spans is not None:
                            self._names[self.norm(cur)] = (cur, spans)
                            if len(spans) == 1 and spans[0][0][:9] in vfs_ekeys:  # nested VFS, e.g. "war3.w3mod:_hd.w3mod"
                                self.vfs_dirs.add(self.norm(cur))
                                self._parse_tvfs(self.read_ekey(spans[0][0]), cur + ":", vfs_ekeys)
                    cur = base

        p, end = path_off, path_off + path_size
        if data[p] == 0xFF:
            val = int.from_bytes(data[p + 1:p + 5], "big")
            end, p = p + 1 + (val & 0x7FFFFFFF), p + 5
        walk(p, end, prefix)

    @staticmethod
    def norm(path: str) -> str:
        return path.replace("\\", "/").lower()

    # public API
    def names(self) -> dict[str, tuple[str, list]]:
        if self._names is None:
            self._load_names()
        return self._names

    def list(self, pattern: str = "") -> list[str]:
        names, pat = self.names(), self.norm(pattern)
        if any(c in pat for c in "*?["):
            return sorted(v[0] for k, v in names.items() if fnmatch.fnmatchcase(k, pat))
        return sorted(v[0] for k, v in names.items() if pat in k)

    def read(self, path: str) -> bytes | None:
        hit = self.names().get(self.norm(path))
        if hit is None:
            return None
        parts = []
        for ekey, _size in hit[1]:
            b = self.read_ekey(ekey)
            if b is None:
                return None  # in the manifest but not downloaded locally
            parts.append(b)
        return b"".join(parts)

    def is_local(self, path: str) -> bool:
        hit = self.names().get(self.norm(path))
        return hit is not None and all((self.locate(e) or (0, 0, 0))[2] > ENTRY_HEADER for e, _ in hit[1])

    def layers(self, hd: bool = False, teen: bool = False, locale: str = "enUS", tileset: str | None = None,
               balance: str | None = None) -> list[str]:
        """Mod prefixes, highest priority first. Order per HiveWE hierarchy; balance mods ("Custom_V0",
        "Custom_V1", "Melee_V0") sit above the base layer. ponytail: _DE.w3mod not layered yet."""
        out = []
        for pre in (["War3.w3mod:_HD.w3mod:"] if hd else []) + ["War3.w3mod:"]:
            if tileset:
                out.append(pre + f"_Tilesets/{tileset}.w3mod:")
            out.append(pre + f"_Locales/{locale}.w3mod:")
            if teen:
                out.append(pre + "_Teen.w3mod:")
            if pre == "War3.w3mod:" and balance:
                out.append(pre + f"_Balance/{balance}.w3mod:")
            out.append(pre)
        out.append("War3.w3mod:_Deprecated.w3mod:")
        return out

    def resolve(self, relpath: str, **layer_kwargs) -> str | None:
        """First existing full path for a mod-relative path like "Units/UnitData.slk"."""
        names = self.names()
        for pre in self.layers(**layer_kwargs):
            hit = names.get(self.norm(pre + relpath))
            if hit is not None:
                return hit[0]
        return None


def open_storage(root) -> Storage:
    return Storage(root)
