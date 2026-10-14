"""Everything the app writes for a user reads like a person wrote it:
plain English, and no em dashes."""

from app.llm.style import STYLE_RULES, plain_english


def test_dashes_become_what_a_person_would_type():
    # One dash joins two thoughts: two sentences read better than a run-on
    # with a comma ("it runs as an agent, it looks up managers").
    assert plain_english("I build systems — and I ship them.") == "I build systems. And I ship them."
    assert plain_english("Scored 1,700 jobs—in under 3 seconds.") == "Scored 1,700 jobs. In under 3 seconds."
    # A pair sets words apart, the way commas do.
    assert plain_english("Two tools — a scraper and a scorer — in a week.") == "Two tools, a scraper and a scorer, in a week."
    # A range of numbers keeps a hyphen, because that's how ranges are written.
    assert plain_english("22–28 minute films") == "22-28 minute films"
    assert plain_english("2019 — 2024") == "2019-2024"


def test_typographic_quotes_become_straight_ones():
    assert plain_english("I didn’t “leverage” anything…") == "I didn't \"leverage\" anything..."


def test_it_leaves_ordinary_writing_alone():
    text = "I led the payments rewrite at Acme. It cut checkout errors by a third."
    assert plain_english(text) == text
    assert plain_english("") == ""
    assert plain_english(None) == ""


def test_a_dash_before_punctuation_doesnt_leave_a_stray_comma():
    assert plain_english("It worked —.") == "It worked."
    assert plain_english("Three things —, then four") == "Three things, then four"


def test_every_prompt_that_writes_for_the_user_carries_the_rules():
    from app.llm.prompts.draft_application_answers import SYSTEM_PROMPT as DRAFT_ANSWERS
    from app.llm.prompts.tailor_resume import (
        ANSWER_PROMPT, COVER_LETTER_PROMPT, OUTREACH_PROMPT, SYSTEM_PROMPT,
    )

    for prompt in (COVER_LETTER_PROMPT, OUTREACH_PROMPT, ANSWER_PROMPT, SYSTEM_PROMPT, DRAFT_ANSWERS):
        assert STYLE_RULES in prompt
        assert "{style}" not in prompt


def test_a_hyphen_used_as_a_dash_counts_as_one():
    from app.llm.style import has_dashes, writing_problems

    # The first real note signed off "Open to a short chat? - Olalekan".
    assert has_dashes("Open to a short chat? - Olalekan")
    assert plain_english("Open to a short chat? - Olalekan") == "Open to a short chat? Olalekan"
    assert plain_english("I built it - it ranks jobs.") == "I built it. It ranks jobs."
    assert writing_problems("I built it - it ranks jobs.") == [
        "It uses a hyphen as a dash. Use a comma or a full stop instead."
    ]
    # Not a range of numbers, a list, or a word with hyphens in it.
    for fine in ("From 2019 - 2021 at Acme.", "Skills:\n- Python\n- FastAPI", "An end-to-end, well-known system."):
        assert not has_dashes(fine), fine
        assert plain_english(fine) == fine
