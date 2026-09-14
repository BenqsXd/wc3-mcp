"""The map's trigger string table (war3map.wts)."""
from ..errors import ToolError
from ..formats.wts import TriggerStrings


def load_strings(project) -> TriggerStrings:
    try:
        return TriggerStrings.parse(project.read("war3map.wts"))
    except ToolError as e:
        if e.code != "no_such_file":
            raise
        return TriggerStrings()
