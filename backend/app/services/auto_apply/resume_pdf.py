"""The tailored resume as a PDF, laid out like the app's print page.

The app's tailored resumes have always been a page the user saves as a PDF
themselves. Sending an application from the server needs a file, so the
same content is rendered here and printed by the browser the sender runs.
"""

from __future__ import annotations

import html
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import CandidateProfile
from app.models.tailoring import TailoredApplication
from app.models.user import User

READY_STATUSES = ("ready", "approved")

_STYLE = """
  @page { size: letter; margin: 0.75in; }
  * { box-sizing: border-box; }
  body { margin: 0; color: #18181b; font: 11pt/1.45 -apple-system, "Helvetica Neue", Helvetica, Arial, sans-serif; }
  h1 { font-size: 24pt; margin: 0; letter-spacing: -0.01em; }
  .headline { margin: 4px 0 0; font-size: 11.5pt; color: #3f3f46; }
  .contact { margin-top: 8px; font-size: 8.5pt; color: #52525b; }
  .contact span + span::before { content: "·"; margin: 0 8px; color: #a1a1aa; }
  header { border-bottom: 1px solid #d4d4d8; padding-bottom: 12px; margin-bottom: 18px; }
  h2 { font-size: 8pt; text-transform: uppercase; letter-spacing: 0.15em; color: #71717a; margin: 0 0 8px; }
  section { margin-bottom: 18px; }
  .role { margin-bottom: 14px; page-break-inside: avoid; }
  .role-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
  .role-title { font-size: 10.5pt; font-weight: 600; margin: 0; }
  .role-title .company { font-weight: 400; color: #3f3f46; }
  .dates { font-size: 8.5pt; color: #71717a; white-space: nowrap; }
  ul { margin: 6px 0 0; padding-left: 16px; }
  li { font-size: 10pt; margin-bottom: 3px; }
  p.summary { font-size: 10pt; margin: 0; }
  .skills { font-size: 10pt; margin: 0; }
"""


def _esc(value: Any) -> str:
    return html.escape(str(value or ""))


def resume_html(data: dict) -> str:
    """`data`: name, headline, contact[], summary, experience[], skills[], education[]."""
    contact = "".join(f"<span>{_esc(item)}</span>" for item in data.get("contact") or [])
    roles = "".join(
        "<div class='role'><div class='role-head'><p class='role-title'>"
        f"{_esc(role.get('title'))}<span class='company'> · {_esc(role.get('company'))}</span></p>"
        f"<span class='dates'>{_esc(role.get('dates'))}</span></div>"
        + ("<ul>" + "".join(f"<li>{_esc(b)}</li>" for b in role.get("bullets") or []) + "</ul>"
           if role.get("bullets") else "")
        + "</div>"
        for role in data.get("experience") or []
    )
    education = "".join(
        f"<div class='role'><div class='role-head'><p class='role-title'>{_esc(item.get('degree') or 'Studied')}"
        f"<span class='company'> · {_esc(item.get('institution'))}</span></p>"
        f"<span class='dates'>{_esc(item.get('dates'))}</span></div></div>"
        for item in data.get("education") or []
    )
    parts = [
        f"<header><h1>{_esc(data.get('name'))}</h1>",
        f"<p class='headline'>{_esc(data['headline'])}</p>" if data.get("headline") else "",
        f"<div class='contact'>{contact}</div></header>",
        f"<section><h2>Summary</h2><p class='summary'>{_esc(data['summary'])}</p></section>" if data.get("summary") else "",
        f"<section><h2>Experience</h2>{roles}</section>" if roles else "",
        f"<section><h2>Skills</h2><p class='skills'>{_esc(' · '.join(data.get('skills') or []))}</p></section>"
        if data.get("skills") else "",
        f"<section><h2>Education</h2>{education}</section>" if education else "",
    ]
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{_esc(data.get('name'))} — Resume</title><style>{_STYLE}</style></head><body>"
        + "".join(parts)
        + "</body></html>"
    )


def _role_dates(entry) -> str:
    start = entry.start_date.strftime("%b %Y") if entry.start_date else ""
    end = entry.end_date.strftime("%b %Y") if entry.end_date else "Present"
    return f"{start} – {end}".strip(" –")


async def tailored_resume_data(db: AsyncSession, user_id, job_id) -> dict | None:
    """The tailored resume for this job, ready to render. None when the job
    has no tailored resume the user could have seen."""
    tailored = (await db.execute(
        select(TailoredApplication)
        .where(
            TailoredApplication.user_id == user_id,
            TailoredApplication.job_id == job_id,
            TailoredApplication.approval_status.in_(READY_STATUSES),
        )
        .order_by(TailoredApplication.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if tailored is None:
        return None
    resume = tailored.tailored_resume_json or {}
    experience = [
        {
            "title": role.get("title"),
            "company": role.get("company"),
            "dates": role.get("dates"),
            "bullets": role.get("bullets") or [],
        }
        for role in resume.get("selected_experience") or []
    ]
    return await _with_profile(db, user_id, {
        "summary": tailored.tailored_summary or resume.get("tailored_summary"),
        "experience": experience,
        "skills": resume.get("highlighted_skills") or [],
    })


async def _with_profile(db: AsyncSession, user_id, data: dict) -> dict:
    """Fill in the facts that come from the profile, not from tailoring."""
    user = await db.get(User, user_id)
    profile = (await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id == user_id).options(
            selectinload(CandidateProfile.work_history),
            selectinload(CandidateProfile.skills),
            selectinload(CandidateProfile.education),
        )
    )).scalar_one_or_none()

    links = (profile.links if profile else None) or {}
    contact = [user.email if user else None, profile.phone if profile else None, profile.current_location if profile else None]
    contact += [str(url).replace("https://", "").replace("http://", "") for url in links.values() if url]

    if not data.get("experience") and profile is not None:
        data["experience"] = [
            {"title": w.title, "company": w.company, "dates": _role_dates(w), "bullets": (w.bullets or [])[:5]}
            for w in sorted(
                profile.work_history,
                key=lambda w: (w.end_date is not None, -(w.start_date.toordinal() if w.start_date else 0)),
            )[:5]
        ]
    else:
        dates = {(w.title or "").lower(): _role_dates(w) for w in (profile.work_history if profile else [])}
        for role in data["experience"]:
            role["dates"] = role.get("dates") or dates.get((role.get("title") or "").lower(), "")

    return {
        "name": (user.name if user else "") or "",
        "headline": profile.headline if profile else None,
        "contact": [c for c in contact if c],
        "summary": data.get("summary") or (profile.master_summary if profile else None),
        "experience": data.get("experience") or [],
        "skills": data.get("skills") or [s.skill_name for s in (profile.skills if profile else [])][:18],
        "education": [
            {"degree": " in ".join(p for p in (e.degree, e.field) if p), "institution": e.institution,
             "dates": e.graduation_date or ""}
            for e in (profile.education if profile else [])
        ],
    }


async def render_pdf(page, html_source: str) -> bytes:
    """Print `html_source` with an already-open Playwright page."""
    await page.set_content(html_source, wait_until="load")
    return await page.pdf(format="Letter", print_background=True)
