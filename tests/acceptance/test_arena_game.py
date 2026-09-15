"""Phase 6 acceptance in the game: each hero-arena variant runs its logic and reports the same results (pytest -m game;
Warcraft III must be logged in to Battle.net once)."""
import pytest

from arena import VARIANTS, build, expected_report, report_file
from wc3mcp.desktop import game


@pytest.mark.game
def test_arena_variants_report_the_same_results(tmp_path):
    project = build(tmp_path / "arena")
    runner = game.Game()
    for variant in VARIANTS:
        built = project["maps"][variant]
        result = runner.test(built["path"], results=[report_file(variant)], timeout=240)
        assert result["missing"] == [], (variant, result)
        assert result["results"][report_file(variant)] == expected_report(built["hero"]), (variant, result)
        assert result["closed"], variant
