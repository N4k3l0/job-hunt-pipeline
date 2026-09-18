"""Everything the app writes for a user reads like a person wrote it:
plain English, and no em dashes."""

from app.llm.style import STYLE_RULES, plain_english


def test_dashes_become_what_a_person_would_type():
    assert plain_english("I build systems — and I ship them.") == "I build systems, and I ship them."
    assert plain_english("Scored 1,700 jobs—in under 3 seconds.") == "Scored 1,700 jobs, in under 3 seconds."
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
    assert plain_english("It worked — well.") == "It worked, well."
    assert plain_english("Three things —, then four") == "Three things, then four"


def test_every_prompt_that_writes_for_the_user_carries_the_rules():
    from app.llm.prompts.draft_application_answers import SYSTEM_PROMPT as DRAFT_ANSWERS
    from app.llm.prompts.tailor_resume import (
        ANSWER_PROMPT, COVER_LETTER_PROMPT, OUTREACH_PROMPT, SYSTEM_PROMPT,
    )

    for prompt in (COVER_LETTER_PROMPT, OUTREACH_PROMPT, ANSWER_PROMPT, SYSTEM_PROMPT, DRAFT_ANSWERS):
        assert STYLE_RULES in prompt
        assert "{style}" not in prompt
