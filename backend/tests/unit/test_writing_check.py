from app.llm.style import writing_problems
from app.services.auto_apply.answers import (
    accept_wording, answer, answer_writing_problems, needs_attention, wording_accepted,
)

WHY = {"key": "why", "label": "Why us?", "type": "textarea", "required": True}


def test_plain_writing_passes():
    assert writing_problems("I built an agent that finds hiring managers. It saves me an hour a day.") == []
    assert writing_problems("We cut costs by 30% in 2023-2024.") == []  # a hyphen in a range is fine


def test_what_gets_flagged():
    problems = writing_problems(
        "I am writing to say I have leveraged AI to build robust systems — fast."
    )
    assert problems == [
        "It has a long dash. Use a comma or a full stop instead.",
        'It uses "leveraged", which people don\'t say out loud. Try "used".',
        'It uses "robust", which people don\'t say out loud. Try "strong".',
        'It says "I am writing to". Say the point straight away.',
    ]
    assert writing_problems(" ".join(["word"] * 45) + ".") == ["One sentence is 45 words long. Split it up."]


def test_a_users_own_answer_is_checked_too():
    dashed = answer("I want this job because I build agents — every day, for real users.", "user")
    assert answer_writing_problems(WHY, dashed)
    assert needs_attention(WHY, dashed)  # confirmed by the user, still not ready


def test_short_facts_are_not_checked():
    name = {"key": "company", "label": "Current company", "type": "text", "required": True}
    assert answer_writing_problems(name, answer("Nakel Media — Lagos", "profile")) == []


def test_fine_as_it_is_covers_words_but_never_dashes():
    wordy = answer("I mapped the whole customer journey for the product and shipped it in six weeks.", "user")
    assert needs_attention(WHY, wordy)
    accepted = accept_wording(wordy)
    assert wording_accepted(accepted) and not needs_attention(WHY, accepted)
    # Changing the text needs accepting again.
    assert not wording_accepted({**accepted, "value": accepted["value"] + " Really."})

    dashed = accept_wording(answer("I mapped the customer journey — and shipped it in six weeks flat.", "user"))
    assert not wording_accepted(dashed) and needs_attention(WHY, dashed)


def test_documents_are_checked():
    from types import SimpleNamespace

    from app.services.auto_apply.writing import document_problems, first_document_problem

    tailored = SimpleNamespace(
        tailored_resume_json={
            "tailored_summary": "I build agents that run in production.",
            "selected_experience": [{"bullets": ["Spearheaded a robust pipeline for 40 clients."]}],
        },
        cover_letter="I am thrilled to apply.",
    )
    problems = document_problems(tailored, with_cover_letter=True)
    assert list(problems) == ["resume", "cover_letter"]
    assert first_document_problem(problems).startswith("Your resume needs plainer wording first: It uses \"spearheaded\"")
    # A cover letter the form doesn't ask for isn't sent, so it isn't checked.
    assert list(document_problems(tailored, with_cover_letter=False)) == ["resume"]
    assert document_problems(None, with_cover_letter=True) == {}
