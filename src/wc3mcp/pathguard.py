from pathlib import Path

from . import config
from .errors import ToolError


def ensure_writable(path) -> Path:
    """Resolve `path` and refuse it if it lies inside the game install (read-only by design)."""
    p = Path(path).resolve()
    root = config.install_root().resolve()
    if p == root or root in p.parents:  # WindowsPath comparisons are case-insensitive
        raise ToolError("install_read_only", f"refusing to write inside the game install: {p}",
                        hint="save under Documents\\Warcraft III\\Maps or another folder")
    return p
