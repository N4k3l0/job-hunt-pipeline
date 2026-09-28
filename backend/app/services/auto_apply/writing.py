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

from app.llm.style import writing_problems
from app.models.auto_apply import AutoApplication
from app.models.tailoring import TailoredApplication
from app.services.auto_apply import answers as rules
from app.services.auto_apply.resume_pdf import tailored_for_job

DOCUMENT_NAMES = {"resume": "Your resume", "cover_letter": "Your cover letter"}


def _unique(problems) -> list[str]:
    return list(dict.fromkeys(problems))


def document_problems(tailored: TailoredApplication | None, *, with_cover_letter: bool) -> dict[str, list[str]]:
    """Problems in the documents written for this job, by document."""
    if tailored is None:
        return {}
    out: dict[str, list[str]] = {}
    resume = tailored.tailored_resume_json or {}
    parts = [resume.get("tailored_summary") or ""] + [
        bullet for role in resume.get("selected_experience") or [] for bullet in role.get("bullets") or []
    ]
    found = _unique(p for part in parts for p in writing_problems(part))
    if found:
        out["resume"] = found
    if with_cover_letter:
        found = writing_problems(tailored.cover_letter)
        if found:
            out["cover_letter"] = found
    return out


def wants_cover_letter(application: AutoApplication) -> bool:
    kinds = rules.kinds(application.form or [], rules.JobFacts(company=""))
    return any(kind == "cover_letter" for kind in kinds.values())


async def application_document_problems(db: AsyncSession, application: AutoApplication) -> dict[str, list[str]]:
    tailored = await tailored_for_job(db, application.user_id, application.job_id)
    return document_problems(tailored, with_cover_letter=wants_cover_letter(application))


def first_document_problem(problems: dict[str, list[str]]) -> str | None:
    """One sentence for an error message, or None."""
    for name, found in problems.items():
        return f"{DOCUMENT_NAMES[name]} needs plainer wording first: {found[0]}"
    return None
