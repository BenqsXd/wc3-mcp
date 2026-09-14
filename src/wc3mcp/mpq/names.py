"""Known Warcraft III archive names and name recovery for maps without a complete (listfile)."""
import re

LOCALES = ("deDE", "enUS", "esES", "esMX", "frFR", "itIT", "jaJP", "koKR", "plPL", "ptBR", "ruRU", "thTH",
           "zhCN", "zhTW")

_BASE = """(listfile) (attributes) (signature) (user data)
war3map.j scripts\\war3map.j war3map.lua scripts\\war3map.lua war3map.w3e war3map.w3i war3map.wtg war3map.wct
war3map.wts war3map.shd war3map.wpm war3map.doo war3mapUnits.doo war3map.w3r war3map.w3c war3map.w3s
war3map.w3u war3map.w3t war3map.w3b war3map.w3d war3map.w3a war3map.w3h war3map.w3q war3map.w3o
war3mapSkin.w3u war3mapSkin.w3t war3mapSkin.w3b war3mapSkin.w3d war3mapSkin.w3a war3mapSkin.w3h war3mapSkin.w3q
war3map.imp war3map.mmp war3mapMap.blp war3mapMap.b00 war3mapMap.tga war3mapPreview.tga war3mapPreview.blp
war3mapPath.tga war3mapMisc.txt war3mapSkin.txt war3mapExtra.txt war3map.wai conversation.json
war3campaign.w3u war3campaign.w3t war3campaign.w3a war3campaign.w3b war3campaign.w3d war3campaign.w3q
war3campaign.w3h war3campaign.w3f war3campaign.imp war3campaign.wts war3campaignSkin.txt war3campaignMisc.txt"""

KNOWN_NAMES = tuple(_BASE.split()) + tuple(f"_Locales\\{loc}.w3mod\\war3map.wts" for loc in LOCALES)

_ASSET = re.compile(rb"[A-Za-z0-9_\-. \\/]{1,200}\.(?:mdx|mdl|blp|dds|tga|jpg|png|wav|mp3|flac|ogg|txt|slk|fdf"
                    rb"|toc|ai|j|lua|json)", re.I)


def _try_read(archive, name: str) -> bytes | None:
    try:
        return archive.read(name)
    except Exception:  # corrupt helper files must not block recovery
        return None


def _import_paths(imp: bytes) -> list[str]:
    count = int.from_bytes(imp[4:8], "little")
    pos, out = 8, []
    for _ in range(min(count, 100_000)):
        end = imp.find(b"\0", pos + 1)
        if pos >= len(imp) or end < 0:
            break
        path = imp[pos + 1:end].decode("utf-8", "replace").replace("/", "\\")
        out += [path, "war3mapImported\\" + path]
        pos = end + 1
    return out


def recover_names(archive) -> list[str]:
    """Names that exist in `archive`, from (listfile), known names, the import list and script string literals."""
    candidates = list(archive.listfile_names()) + list(KNOWN_NAMES)
    imp = _try_read(archive, "war3map.imp")
    if imp and len(imp) >= 8:
        candidates += _import_paths(imp)
    for script in ("war3map.j", "scripts\\war3map.j", "war3map.lua", "scripts\\war3map.lua"):
        for m in _ASSET.finditer(_try_read(archive, script) or b""):
            candidates.append(m.group().decode("latin-1").strip().replace("\\\\", "\\"))
    seen, out = set(), []
    for name in (c.replace("/", "\\") for c in candidates):
        key = name.upper()
        if key not in seen and archive.find(name) is not None:
            seen.add(key)
            out.append(name)
    return out
