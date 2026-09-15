"""The trigger string table (war3map.wts, or war3campaign.wts in a campaign)."""
from ..errors import ToolError
from ..formats.wts import TriggerStrings


def file_prefix(project) -> str:
    """Name stem of the strings, object data and imports files: war3campaign in a campaign (.w3n), else war3map."""
    return "war3campaign" if any(f["name"].lower() == "war3campaign.w3f" for f in project.list_files()) else "war3map"


def strings_file(project) -> str:
    return file_prefix(project) + ".wts"


def load_strings(project) -> TriggerStrings:
    try:
        return TriggerStrings.parse(project.read(strings_file(project)))
    except ToolError as e:
        if e.code != "no_such_file":
            raise
        return TriggerStrings()
