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
        validation_notes=None,
    )
    problems = document_problems(tailored, with_cover_letter=True)
    assert list(problems) == ["resume", "cover_letter"]
    assert first_document_problem(problems).startswith("Your resume needs plainer wording first: It uses \"spearheaded\"")
    # A cover letter the form doesn't ask for isn't sent, so it isn't checked.
    assert list(document_problems(tailored, with_cover_letter=False)) == ["resume"]
    assert document_problems(None, with_cover_letter=True) == {}


async def test_dashes_are_rewritten_by_the_model_not_swapped_for_commas():
    from app.llm.style import without_dashes

    class Model:
        calls = 0

        async def generate(self, task, system, text, max_tokens=0):
            Model.calls += 1
            assert task == "review" and "long dash" in system
            return "My platform runs as an agent. It looks up hiring managers."

    assert await without_dashes("My platform runs as an agent — it looks up hiring managers.", Model()) == (
        "My platform runs as an agent. It looks up hiring managers."
    )
    # No dash, no call.
    assert await without_dashes("Nothing to fix here.", Model()) == "Nothing to fix here."
    assert Model.calls == 1

    class Broken:
        async def generate(self, *args, **kwargs):
            raise RuntimeError("AI is paused")

    # The fallback still takes the dash out, as a full stop.
    assert await without_dashes("It runs as an agent — it looks up managers.", Broken()) == (
        "It runs as an agent. It looks up managers."
    )


async def test_documents_are_read_through_once_per_version():
    from types import SimpleNamespace

    from app.llm.style import NOT_READ_YET
    from app.services.auto_apply.writing import document_problems, read_documents_through

    tailored = SimpleNamespace(
        tailored_resume_json={"tailored_summary": "I build agents that run in production for real users."},
        cover_letter="Hi, I build agents that run in production.",
        validation_notes={"strongest_matches": ["Python"]},
    )
    assert document_problems(tailored, with_cover_letter=True) == {
        "resume": [NOT_READ_YET], "cover_letter": [NOT_READ_YET],
    }

    read = []

    async def reader(text, *, what):
        read.append(what)
        return ['"run in production": say who uses them instead.'] if "cover letter" in what else []

    assert await read_documents_through(tailored, with_cover_letter=True, reader=reader) == 0
    assert document_problems(tailored, with_cover_letter=True) == {
        "cover_letter": ['"run in production": say who uses them instead.'],
    }
    assert tailored.validation_notes["strongest_matches"] == ["Python"]  # left alone

    await read_documents_through(tailored, with_cover_letter=True, reader=reader)
    assert len(read) == 2  # nothing changed, nothing read again

    tailored.cover_letter = "Hi, I build agents people use every day."
    assert document_problems(tailored, with_cover_letter=True) == {"cover_letter": [NOT_READ_YET]}


def test_findings_come_back_in_whatever_shape_the_model_sends():
    from app.llm.style import _problems_from

    assert _problems_from([{"quote": "load-bearing step", "fix": "Say each step."}]) == ['"load-bearing step": Say each step.']
    assert _problems_from(["Split the second sentence."]) == ["Split the second sentence."]
    assert _problems_from('[{"quote": "synergy", "fix": "Cut it."}]') == ['"synergy": Cut it.']
    assert _problems_from(None) == [] and _problems_from([{"quote": "", "fix": "x"}]) == []


async def test_revise_keeps_the_lines_when_the_answer_doesnt_fit():
    from app.llm.style import revise_plainly

    class Model:
        def __init__(self, lines):
            self.lines = lines

        async def generate_structured(self, task, system, prompt, tools, max_tokens=0):
            assert task == "review" and "Keep every fact" in prompt
            return {"lines": self.lines}

    lines = ["I tuned cost at each load-bearing step.", "I built a bot."]
    assert await revise_plainly(lines, ['"load-bearing step": say each step'], what="a resume",
                                llm=Model(["1. I tuned the cost of each step.", "I built a bot."])) == [
        "I tuned the cost of each step.", "I built a bot.",
    ]
    assert await revise_plainly(lines, ["x"], what="a resume", llm=Model(["only one line"])) == lines
    assert await revise_plainly(lines, [], what="a resume", llm=Model([])) == lines


async def test_documents_are_fixed_before_anyone_sees_them():
    from types import SimpleNamespace

    from app.services.auto_apply.writing import document_problems, make_documents_plain

    tailored = SimpleNamespace(
        tailored_resume_json={
            "tailored_summary": "Engineer tuning cost at each load-bearing step in the agent chain.",
            "selected_experience": [{"bullets": ["Built a voice bot for a gym that books classes."]}],
        },
        tailored_summary="Engineer tuning cost at each load-bearing step in the agent chain.",
        cover_letter=None,
        validation_notes=None,
    )

    async def reader(text, *, what):
        return ['"load-bearing step": say each step.'] if "load-bearing" in text else []

    async def reviser(lines, problems, *, what):
        return [line.replace("at each load-bearing step in the agent chain", "at each step") for line in lines]

    assert await make_documents_plain(tailored, with_cover_letter=False, reader=reader, reviser=reviser) == 0
    assert tailored.tailored_summary == "Engineer tuning cost at each step."
    assert tailored.tailored_resume_json["selected_experience"][0]["bullets"] == [
        "Built a voice bot for a gym that books classes.",
    ]
    assert document_problems(tailored, with_cover_letter=False) == {}
