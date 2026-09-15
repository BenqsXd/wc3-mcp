"""Phase 6 acceptance, tool level: the hero-arena project builds through the MCP tools, validates and reopens with
everything in place."""
import pytest

from arena import VARIANTS, build, check_campaign, check_map
from corpus import HAVE_INSTALL

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    return build(tmp_path_factory.mktemp("arena"))


@pytest.mark.parametrize("variant", VARIANTS)
def test_maps_reopen_with_everything_in_place(project, variant):
    check_map(project["maps"][variant], variant)


def test_campaign_holds_two_maps(project):
    check_campaign(project["campaign"])
