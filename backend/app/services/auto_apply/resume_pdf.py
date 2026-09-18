"""The tailored resume and cover letter as PDFs the app can attach.

Tailored resumes used to exist only as a page the user saved as a PDF
themselves. Applications need a file, so they're drawn here instead, with
a plain typographic layout that reads the same as the print page.
"""

from __future__ import annotations

from typing import Any

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import CandidateProfile
from app.models.tailoring import TailoredApplication
from app.models.user import User

READY_STATUSES = ("ready", "approved")

# The core PDF fonts only speak latin-1, and written text is full of
# typographic characters. Swap the common ones rather than ship a font.
_REPLACEMENTS = {
    "—": "-", "–": "-", "‒": "-", "−": "-",
    "‘": "'", "’": "'", "‚": ",", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "•": "-", "‣": "-", "●": "-", "▪": "-",
    "…": "...", " ": " ", "→": "->", "≥": ">=", "≤": "<=",
}

INK = (24, 24, 27)
MUTED = (82, 82, 91)
FAINT = (113, 113, 122)
RULE = (212, 212, 216)


def _text(value: Any) -> str:
    text = str(value or "")
    for bad, good in _REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


class _Page(FPDF):
    def __init__(self) -> None:
        super().__init__(format="letter", unit="mm")
        self.set_auto_page_break(auto=True, margin=19)
        self.set_margins(19, 19, 19)
        self.add_page()

    def heading(self, label: str) -> None:
        self.ln(3)
        self.set_font("helvetica", "B", 8)
        self.set_text_color(*FAINT)
        self.cell(0, 4, _text(label.upper()), new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body(self, text: str, size: float = 10, style: str = "", color=INK, height: float = 4.6) -> None:
        self.set_font("helvetica", style, size)
        self.set_text_color(*color)
        self.multi_cell(0, height, _text(text), align="L", new_x="LMARGIN", new_y="NEXT")

    def rule(self) -> None:
        self.ln(2)
        self.set_draw_color(*RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)


def _header(pdf: _Page, data: dict) -> None:
    pdf.set_font("helvetica", "B", 20)
    pdf.set_text_color(*INK)
    pdf.cell(0, 9, _text(data.get("name")), new_x="LMARGIN", new_y="NEXT")
    if data.get("headline"):
        pdf.body(data["headline"], size=10.5, color=MUTED, height=5)
    contact = " · ".join(_text(item) for item in (data.get("contact") or []))
    if contact:
        pdf.body(contact, size=8.5, color=FAINT, height=4)
    pdf.rule()


def _experience(pdf: _Page, roles: list[dict]) -> None:
    for role in roles:
        title = _text(role.get("title"))
        company = _text(role.get("company"))
        dates = _text(role.get("dates"))
        pdf.set_font("helvetica", "B", 10.5)
        pdf.set_text_color(*INK)
        width = pdf.get_string_width(title)
        pdf.cell(width + 1, 5, title)
        pdf.set_font("helvetica", "", 10.5)
        pdf.set_text_color(*MUTED)
        rest = f" · {company}" if company else ""
        pdf.cell(pdf.get_string_width(rest) + 1, 5, rest)
        if dates:
            pdf.set_font("helvetica", "", 8.5)
            pdf.set_text_color(*FAINT)
            pdf.cell(0, 5, dates, align="R")
        pdf.ln(5)
        for bullet in role.get("bullets") or []:
            pdf.set_font("helvetica", "", 10)
            pdf.set_text_color(*INK)
            pdf.set_x(pdf.l_margin + 3)
            pdf.multi_cell(0, 4.6, f"- {_text(bullet)}", align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)


def build_resume_pdf(data: dict) -> bytes:
    """`data`: name, headline, contact[], summary, experience[], skills[], education[]."""
    pdf = _Page()
    _header(pdf, data)
    if data.get("summary"):
        pdf.heading("Summary")
        pdf.body(data["summary"])
    if data.get("experience"):
        pdf.heading("Experience")
        _experience(pdf, data["experience"])
    if data.get("skills"):
        pdf.heading("Skills")
        pdf.body(" · ".join(_text(skill) for skill in data["skills"]))
    if data.get("education"):
        pdf.heading("Education")
        _experience(pdf, [
            {"title": item.get("degree") or "Studied", "company": item.get("institution"), "dates": item.get("dates")}
            for item in data["education"]
        ])
    return bytes(pdf.output())


def build_letter_pdf(data: dict, letter: str) -> bytes:
    """A cover letter on the same letterhead as the resume."""
    pdf = _Page()
    _header(pdf, data)
    for paragraph in [p.strip() for p in str(letter or "").split("\n") if p.strip()]:
        pdf.body(paragraph, height=5)
        pdf.ln(2)
    return bytes(pdf.output())


def _role_dates(entry) -> str:
    start = entry.start_date.strftime("%b %Y") if entry.start_date else ""
    end = entry.end_date.strftime("%b %Y") if entry.end_date else "Present"
    return f"{start} - {end}".strip(" -")


async def tailored_for_job(db: AsyncSession, user_id, job_id) -> TailoredApplication | None:
    """The tailored application for this job, if the user has one ready."""
    return (await db.execute(
        select(TailoredApplication)
        .where(
            TailoredApplication.user_id == user_id,
            TailoredApplication.job_id == job_id,
            TailoredApplication.approval_status.in_(READY_STATUSES),
        )
        .order_by(TailoredApplication.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()


async def resume_data(db: AsyncSession, user_id, tailored: TailoredApplication | None) -> dict:
    """What to draw: the tailored resume when there is one, else the
    profile's own summary, roles and skills."""
    resume = (tailored.tailored_resume_json if tailored else None) or {}
    experience = [
        {"title": role.get("title"), "company": role.get("company"),
         "dates": role.get("dates"), "bullets": role.get("bullets") or []}
        for role in resume.get("selected_experience") or []
    ]
    user = await db.get(User, user_id)
    profile = (await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id == user_id).options(
            selectinload(CandidateProfile.work_history),
            selectinload(CandidateProfile.skills),
            selectinload(CandidateProfile.education),
        )
    )).scalar_one_or_none()

    links = (profile.links if profile else None) or {}
    contact = [user.email if user else None, profile.phone if profile else None,
               profile.current_location if profile else None]
    contact += [str(url).replace("https://", "").replace("http://", "") for url in links.values() if url]

    history = sorted(
        (profile.work_history if profile else []),
        key=lambda w: (w.end_date is not None, -(w.start_date.toordinal() if w.start_date else 0)),
    )
    if experience:
        dates = {(w.title or "").lower(): _role_dates(w) for w in history}
        for role in experience:
            role["dates"] = role.get("dates") or dates.get((role.get("title") or "").lower(), "")
    else:
        experience = [
            {"title": w.title, "company": w.company, "dates": _role_dates(w), "bullets": (w.bullets or [])[:5]}
            for w in history[:5]
        ]

    summary = (tailored.tailored_summary if tailored else None) or resume.get("tailored_summary")
    skills = resume.get("highlighted_skills") or [s.skill_name for s in (profile.skills if profile else [])][:18]
    return {
        "name": (user.name if user else "") or "",
        "headline": profile.headline if profile else None,
        "contact": [c for c in contact if c],
        "summary": summary or (profile.master_summary if profile else None),
        "experience": experience,
        "skills": skills,
        "education": [
            {"degree": " in ".join(p for p in (e.degree, e.field) if p), "institution": e.institution,
             "dates": e.graduation_date or ""}
            for e in (profile.education if profile else [])
        ],
    }
