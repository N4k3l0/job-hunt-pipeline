"""The board names the lookup guesses for a company."""

from app.services.discovery.ats_resolver import _slug_candidates


def test_first_word_alone_only_when_the_rest_is_generic():
    assert "wayve" in _slug_candidates("Wayve Technologies")
    assert "anthropic" in _slug_candidates("Anthropic PBC")
    # Other companies' boards: Parker Hannifin isn't "parker", Blue Chip
    # Talent isn't "blue", Focus Engineering isn't "focus".
    assert "parker" not in _slug_candidates("Parker Hannifin")
    assert "blue" not in _slug_candidates("Blue Chip Talent")
    assert "focus" not in _slug_candidates("Focus Engineering B.V.")
    assert _slug_candidates("Scout Motors Inc.")[:2] == ["scout-motors", "scoutmotors"]
