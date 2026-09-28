"""Check the writing an application sends before calling it ready.

Everything that goes to a company has to read like the person wrote it:
no long dashes, plain simple English, nothing stiff (llm/style.py). That
covers the form's written answers (answers.py checks those, including ones
the user typed or pasted) and the documents attached here: the tailored
resume's summary and bullets, and the cover letter when the form asks for
one. An application with anything flagged is never "ready to send".
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

import asyncio
import logging

from app.llm.style import NOT_READ_YET, fingerprint, has_dashes, read_through, revise_plainly, writing_problems
from app.models.auto_apply import AutoApplication
from app.models.tailoring import TailoredApplication
from app.services.auto_apply import answers as rules
from app.services.auto_apply.resume_pdf import tailored_for_job

logger = logging.getLogger(__name__)

DOCUMENT_NAMES = {"resume": "Your resume", "cover_letter": "Your cover letter"}
DOCUMENT_WHAT = {
    "resume": "the summary and bullet points of a resume written for this job (short, clipped lines are normal)",
    "cover_letter": "a cover letter",
}


def _resume_parts(tailored: TailoredApplication) -> list[str]:
    resume = tailored.tailored_resume_json or {}
    return [resume.get("tailored_summary") or ""] + [
        bullet for role in resume.get("selected_experience") or [] for bullet in role.get("bullets") or []
    ]


def _document_texts(tailored: TailoredApplication, with_cover_letter: bool) -> dict[str, str]:
    texts = {"resume": "\n".join(p for p in _resume_parts(tailored) if p.strip())}
    if with_cover_letter:
        texts["cover_letter"] = tailored.cover_letter or ""
    return {name: text for name, text in texts.items() if text.strip()}


def _read(tailored: TailoredApplication) -> dict:
    return dict((tailored.validation_notes or {}).get("read_through") or {})


async def read_documents_through(tailored: TailoredApplication | None, *, with_cover_letter: bool, reader=None) -> int:
    """Have the model read the documents it hasn't read in their current
    words, and keep what it found with them. Returns how many couldn't be
    read; those stay "not read yet". The caller commits."""
    if tailored is None:
        return 0
    reader = reader or read_through
    done = _read(tailored)
    todo = {
        name: text for name, text in _document_texts(tailored, with_cover_letter).items()
        if (done.get(name) or {}).get("fp") != fingerprint(text)
    }
    if not todo:
        return 0
    results = await asyncio.gather(
        *(reader(text, what=DOCUMENT_WHAT[name]) for name, text in todo.items()), return_exceptions=True,
    )
    failed = 0
    for (name, text), found in zip(todo.items(), results):
        if isinstance(found, Exception):
            failed += 1
            logger.warning("Couldn't read the %s through: %s", name, found)
            continue
        done[name] = {"fp": fingerprint(text), "problems": found}
    tailored.validation_notes = {**(tailored.validation_notes or {}), "read_through": done}
    return failed


def _unique(problems) -> list[str]:
    return list(dict.fromkeys(problems))


async def make_documents_plain(
    tailored: TailoredApplication | None, *, with_cover_letter: bool = True, reader=None, reviser=None,
) -> int:
    """Read the documents through, fix what was found (same facts, nothing
    added), and read them again, so what reaches the user already reads
    plainly and only what's left is flagged. Returns how many couldn't be
    read. The caller commits."""
    if tailored is None:
        return 0
    reviser = reviser or revise_plainly
    failed = await read_documents_through(tailored, with_cover_letter=with_cover_letter, reader=reader)
    found = document_problems(tailored, with_cover_letter=with_cover_letter)
    changed = False

    resume_problems = [p for p in found.get("resume", []) if p != NOT_READ_YET]
    if resume_problems:
        resume = dict(tailored.tailored_resume_json or {})
        roles = [dict(role) for role in resume.get("selected_experience") or []]
        lines = [resume.get("tailored_summary") or ""] + [b for role in roles for b in role.get("bullets") or []]
        try:
            revised = await reviser(lines, resume_problems, what="a resume summary followed by its bullet points")
        except Exception as e:  # noqa: BLE001 — the problems stay flagged for the user
            logger.warning("Couldn't revise the resume: %s", e)
            revised = lines
        if revised != lines:
            summary, bullets = revised[0], revised[1:]
            for role in roles:
                count = len(role.get("bullets") or [])
                role["bullets"], bullets = bullets[:count], bullets[count:]
            resume.update(tailored_summary=summary, selected_experience=roles)
            tailored.tailored_resume_json = resume
            tailored.tailored_summary = summary
            changed = True

    letter_problems = [p for p in found.get("cover_letter", []) if p != NOT_READ_YET]
    if letter_problems and tailored.cover_letter:
        paragraphs = tailored.cover_letter.split("\n\n")
        try:
            revised = await reviser(paragraphs, letter_problems, what="a cover letter, one paragraph per line")
        except Exception as e:  # noqa: BLE001
            logger.warning("Couldn't revise the cover letter: %s", e)
            revised = paragraphs
        if revised != paragraphs:
            tailored.cover_letter = "\n\n".join(revised)
            changed = True

    if changed:
        failed = await read_documents_through(tailored, with_cover_letter=with_cover_letter, reader=reader)
    return failed


def document_problems(tailored: TailoredApplication | None, *, with_cover_letter: bool) -> dict[str, list[str]]:
    """Problems in the documents written for this job, by document."""
    if tailored is None:
        return {}
    out: dict[str, list[str]] = {}
    done = _read(tailored)
    texts = _document_texts(tailored, with_cover_letter)
    checked = {
        "resume": _unique(p for part in _resume_parts(tailored) for p in writing_problems(part)),
        "cover_letter": writing_problems(tailored.cover_letter) if with_cover_letter else [],
    }
    for name, found in checked.items():
        if name in texts:
            read = done.get(name) or {}
            text_fp = fingerprint(texts[name])
            if read.get("accepted") == text_fp and not has_dashes(texts[name]):
                continue  # the user said this version is fine as it is
            if read.get("fp") != text_fp:
                found = found + [NOT_READ_YET]
            else:
                found = _unique(found + read.get("problems", []))
        if found:
            out[name] = found
    return out


def accept_document_wording(tailored: TailoredApplication, name: str, *, with_cover_letter: bool) -> None:
    """The user keeps this version of a document despite what was flagged.
    Long dashes still have to come out. The caller commits."""
    text = _document_texts(tailored, with_cover_letter).get(name)
    if not text:
        raise ValueError("That document isn't sent with this application.")
    if has_dashes(text):
        raise ValueError("Take the long dashes out first. The rest can stay as it is.")
    done = _read(tailored)
    done[name] = {**(done.get(name) or {}), "accepted": fingerprint(text)}
    tailored.validation_notes = {**(tailored.validation_notes or {}), "read_through": done}


def wants_cover_letter(application: AutoApplication) -> bool:
    kinds = rules.kinds(application.form or [], rules.JobFacts(company=""))
    return any(kind == "cover_letter" for kind in kinds.values())


async def application_document_problems(
    db: AsyncSession, application: AutoApplication, *, read: bool = True,
) -> dict[str, list[str]]:
    """Problems in the documents this application sends. With `read`, any
    the model hasn't read in their current words are read first."""
    tailored = await tailored_for_job(db, application.user_id, application.job_id)
    with_cover_letter = wants_cover_letter(application)
    if read and tailored is not None:
        before = dict(tailored.validation_notes or {})
        await read_documents_through(tailored, with_cover_letter=with_cover_letter)
        if tailored.validation_notes != before:
            await db.commit()
    return document_problems(tailored, with_cover_letter=with_cover_letter)


def first_document_problem(problems: dict[str, list[str]]) -> str | None:
    """One sentence for an error message, or None."""
    for name, found in problems.items():
        return f"{DOCUMENT_NAMES[name]} needs plainer wording first: {found[0]}"
    return None
