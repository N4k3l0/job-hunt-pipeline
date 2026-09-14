"""Fill in an application form from what the app knows about the user.

Every answer records where it came from and whether it's confirmed:

    profile  the user's profile or resume (confirmed)
    saved    what the user answered to the same question before (confirmed)
    default  a safe choice: declining voluntary demographic questions and
             marketing messages (confirmed)
    suggested / drafted
             a likely answer the user still has to confirm
    user     entered or confirmed by the user

The app never confirms an answer it isn't sure of. Legal agreements and
attestations are always left for the user, even when required.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from app.services.jobs_filter import work_eligible_countries

COUNTRY_NAMES = {
    "NL": "Netherlands", "DE": "Germany", "IE": "Ireland", "GB": "United Kingdom", "US": "United States",
    "CA": "Canada", "FR": "France", "ES": "Spain", "PT": "Portugal", "IT": "Italy", "BE": "Belgium",
    "LU": "Luxembourg", "AT": "Austria", "CH": "Switzerland", "SE": "Sweden", "DK": "Denmark", "NO": "Norway",
    "FI": "Finland", "IS": "Iceland", "PL": "Poland", "CZ": "Czech Republic", "EE": "Estonia", "LV": "Latvia",
    "LT": "Lithuania", "AU": "Australia", "NZ": "New Zealand", "SG": "Singapore", "JP": "Japan", "IN": "India",
    "AE": "United Arab Emirates", "NG": "Nigeria", "KE": "Kenya", "ZA": "South Africa", "GH": "Ghana",
    "EG": "Egypt", "BR": "Brazil", "MX": "Mexico", "AR": "Argentina",
}
_COUNTRY_ALIASES = {
    "US": ["united states of america", "united states", "usa", "u.s.a.", "u.s."],
    "GB": ["united kingdom", "great britain", "britain", "england", "u.k."],
    "CZ": ["czechia"],
    "AE": ["uae"],
    "NL": ["the netherlands", "holland"],
}
# Uppercase abbreviations that are also ordinary words in lowercase ("us").
_CASE_SENSITIVE_ALIASES = {"US": ["US"], "GB": ["UK"]}

SOURCES_CONFIRMED = {"profile", "saved", "default", "user"}


@dataclass
class ApplicantFacts:
    full_name: str
    email: str
    phone: str | None = None
    location: str | None = None
    home_country: str | None = None
    visa_statuses: dict = field(default_factory=dict)
    links: dict = field(default_factory=dict)
    current_company: str | None = None
    current_title: str | None = None
    past_employers: list[str] = field(default_factory=list)
    years_experience: float | None = None
    salary_min: int | None = None
    salary_currency: str | None = None
    has_resume: bool = False


@dataclass
class JobFacts:
    company: str
    country: str | None = None


# ─── Helpers ────────────────────────────────────────────────────────────────


def normalize_label(label: str) -> str:
    text = (label or "").replace("✱", " ").replace("*", " ").lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ?:.!").strip()


def question_key(item: dict) -> str:
    family = "choice" if item["type"] in ("select", "multiselect", "boolean") else "text"
    return hashlib.sha256(f"{family}:{normalize_label(item['label'])}".encode()).hexdigest()


def answer(value, source: str, note: str | None = None) -> dict:
    return {"value": value, "source": source, "confirmed": source in SOURCES_CONFIRMED, "note": note}


def is_empty(value) -> bool:
    return value is None or value == "" or value == []


def countries_in(text: str) -> list[str]:
    """ISO codes of countries named in a question."""
    found: list[str] = []
    lowered = f" {text.lower()} "
    for code, name in COUNTRY_NAMES.items():
        names = [name.lower()] + _COUNTRY_ALIASES.get(code, [])
        if any(re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", lowered) for n in names):
            found.append(code)
    for code, abbreviations in _CASE_SENSITIVE_ALIASES.items():
        if code not in found and any(re.search(rf"\b{a}\b", text) for a in abbreviations):
            found.append(code)
    return found


def choose_option(item: dict, *wanted: str) -> str | None:
    """Value of the first option whose label starts with one of `wanted`
    as whole words ("no" matches "No, thanks" but not "None")."""
    for w in wanted:
        pattern = re.compile(rf"{re.escape(w)}(?![a-z0-9])")
        for option in item.get("options") or []:
            if pattern.match(normalize_label(option["label"])):
                return option["value"]
    return None


def yes_no(item: dict, yes: bool):
    """A yes/no answer in the field's own format, or None if the field
    has no clear yes/no choice."""
    if item["type"] == "boolean":
        return yes
    if item["type"] in ("select", "multiselect"):
        value = choose_option(item, "yes" if yes else "no")
        if value is None:
            return None
        return [value] if item["type"] == "multiselect" else value
    return "Yes" if yes else "No"


# ─── Classification ─────────────────────────────────────────────────────────

_AGREEMENT = re.compile(
    r"\b(agree|agreement|acknowledg|certify|certification|attest|consent to|terms|arbitrat|"
    r"privacy (notice|policy)|policy|i have read|i confirm|declaration)\w*",
)
_VOLUNTARY = re.compile(
    r"\b(gender|race|racial|ethnicity|ethnic|hispanic|latino|veteran|disability|disabled|"
    r"sexual orientation|transgender|lgbt|pronoun)\w*",
)
_DECLINE = re.compile(
    r"(decline|prefer not|don.?t wish|do not wish|do not want|don.?t want|not to (answer|disclose|say|self)|"
    r"choose not|rather not|i don.?t know)",
)


def classify(item: dict, job: JobFacts) -> str:
    key = item["key"].lower()
    label = normalize_label(item["label"])
    type_ = item["type"]
    company = normalize_label(job.company)

    if item.get("group") == "voluntary":
        return "voluntary"
    if type_ == "file":
        return "cover_letter" if "cover" in key or "cover letter" in label else "resume"
    if key in ("first_name",) or re.fullmatch(r"(legal )?first name", label):
        return "first_name"
    if key in ("last_name",) or re.fullmatch(r"(legal )?(last name|surname|family name)", label):
        return "last_name"
    if "preferred" in label and "name" in label:
        return "preferred_name"
    if key in ("name", "_systemfield_name") or re.fullmatch(r"(full |legal )?name", label):
        return "full_name"
    if type_ == "email" or label in ("email", "email address"):
        return "email"
    if type_ == "phone" or re.fullmatch(r"(phone|mobile|telephone)( number)?", label):
        return "phone"
    if "linkedin" in key or "linkedin" in label:
        return "linkedin"
    if "github" in key or "github" in label:
        return "github"
    if re.search(r"urls\[portfolio\]", key) or re.fullmatch(r"(portfolio|personal website|website)( url| link)?", label):
        return "portfolio"
    if key == "org" or re.search(r"(current|most recent|previous) (company|employer)|who is your current", label):
        return "current_company"
    if re.search(r"(current|most recent) (or previous )?(job )?title", label):
        return "current_title"
    if key == "consent[marketing]" or re.search(
        r"\b(opt.?in|whatsapp|sms|text messages|newsletter|marketing|talent (community|network)|future (job )?opportunities)\b",
        label,
    ):
        # A required checkbox can't be declined, only ticked: that's the
        # user's call. A required yes/no question can be answered "No".
        return "agreement" if item["required"] and type_ == "boolean" else "marketing"
    if _AGREEMENT.search(label) or any(_AGREEMENT.search(normalize_label(o["label"])) for o in item.get("options") or []):
        return "agreement"
    if _VOLUNTARY.search(label):
        return "voluntary"
    if re.search(r"\b(sponsor|sponsorship)\b", label):
        return "sponsorship"
    if re.search(r"\b(authori[sz]ed|legally (able|allowed|permitted|eligible)|right to work|work (permit|authori[sz]ation)|eligible to work)\b", label):
        return "work_authorization"
    if re.search(r"countr(y|ies) (where|in which) you (currently )?(reside|live)|country of residence|what country do you (currently )?live", label):
        return "country_of_residence"
    if type_ == "location" or re.fullmatch(r"(current )?(location|city)|where are you (currently )?(located|based)", label):
        return "location"
    if company and company in label and re.search(r"\b(employed|worked|interviewed|applied)\b", label):
        return "previous_company_contact"
    if re.fullmatch(r"(how many )?years of (professional |relevant |work |full.?time )?experience( do you have)?", label):
        return "years_experience"
    if re.search(r"\b(salary|compensation|pay) (expectation|requirement)s?|expected (salary|compensation)|desired (salary|compensation)", label):
        return "salary"
    if key == "pronouns" or label == "pronouns":
        return "voluntary"
    return "question"


# ─── Rules ──────────────────────────────────────────────────────────────────


def _question_country(item: dict, job: JobFacts) -> str | None:
    named = countries_in(f"{item['label']} {item.get('description') or ''}")
    if len(named) == 1:
        return named[0]
    if named:
        return None
    if re.search(
        r"(where|in which) (the|this) (job|role|position)|in this country|for this (job|role|position)|the job'?s? location",
        normalize_label(item["label"]),
    ):
        return job.country
    return None


def _country_option(item: dict, code: str) -> str | None:
    """Option naming the country, else "Other" when the country isn't listed."""
    options = item.get("options") or []
    for option in options:
        if code in countries_in(option["label"]):
            return option["value"]
    return choose_option(item, "other")


def _from_profile(item: dict, kind: str, facts: ApplicantFacts, job: JobFacts) -> dict | None:
    names = facts.full_name.split()
    simple = {
        "first_name": names[0] if names else None,
        "last_name": " ".join(names[1:]) if len(names) > 1 else None,
        "full_name": facts.full_name or None,
        "email": facts.email or None,
        "phone": facts.phone,
        "location": facts.location,
        "linkedin": facts.links.get("linkedin"),
        "github": facts.links.get("github"),
        "portfolio": facts.links.get("portfolio") or facts.links.get("website"),
        "current_company": facts.current_company,
        "current_title": facts.current_title,
    }
    if kind in simple:
        value = simple[kind]
        if is_empty(value):
            hint = {"phone": "Add your phone number to your profile to fill this in next time.",
                    "location": "Add your current location to your profile to fill this in next time."}.get(kind)
            return {"value": None, "source": None, "confirmed": False, "note": hint} if hint else None
        if item["type"] in ("select", "multiselect"):
            return None
        return answer(value, "profile")

    if kind == "resume":
        return answer("resume", "profile") if facts.has_resume else {
            "value": None, "source": None, "confirmed": False, "note": "Upload your resume first."}

    if kind == "country_of_residence" and facts.home_country:
        if item["type"] in ("select", "multiselect"):
            value = _country_option(item, facts.home_country)
            if value is not None:
                return answer([value] if item["type"] == "multiselect" else value, "profile")
            return None
        return answer(COUNTRY_NAMES.get(facts.home_country, facts.home_country), "profile")

    if kind in ("work_authorization", "sponsorship"):
        country = _question_country(item, job)
        if not country:
            return None
        status = (facts.visa_statuses or {}).get(country)
        can_work = country in work_eligible_countries(facts.home_country, facts.visa_statuses)
        where = COUNTRY_NAMES.get(country, country)
        if kind == "work_authorization":
            if can_work:
                value = yes_no(item, True)
            elif status == "need_sponsorship":
                value = yes_no(item, False)
            else:
                return {"value": None, "source": None, "confirmed": False,
                        "note": f"Your profile doesn't say whether you can work in {where}."}
        else:
            if country == facts.home_country or status in ("citizen", "permanent_resident"):
                value = yes_no(item, False)
            elif status == "need_sponsorship":
                value = yes_no(item, True)
            else:
                return {"value": None, "source": None, "confirmed": False,
                        "note": f"Only you know whether you'll need sponsorship to work in {where}."}
        return answer(value, "profile", f"Based on your work rights in {where}.") if value is not None else None
    return None


def _saved(item: dict, saved: dict[str, dict]) -> dict | None:
    """The user's earlier answer to the same question. Answers older than
    SAVED_ANSWER_FRESH_DAYS are offered for confirmation instead, since
    things like start dates and salary change."""
    stored = saved.get(question_key(item))
    if not stored:
        return None
    source = "saved" if stored.get("fresh") else "suggested"
    note = None if stored.get("fresh") else "You gave this answer on an earlier application."
    if item["type"] in ("select", "multiselect", "boolean"):
        labels = [normalize_label(l) for l in stored.get("labels") or []]
        if not labels:
            return None
        if item["type"] == "boolean":
            if labels[0] in ("yes", "true"):
                return answer(True, source, note)
            if labels[0] in ("no", "false"):
                return answer(False, source, note)
            return None
        by_label = {normalize_label(o["label"]): o["value"] for o in item.get("options") or []}
        if not all(l in by_label for l in labels):
            return None
        values = [by_label[l] for l in labels]
        if item["type"] == "select":
            return answer(values[0], source, note) if len(values) == 1 else None
        return answer(values, source, note)
    text = stored.get("text")
    return answer(text, source, note) if text else None


SAVED_ANSWER_FRESH_DAYS = 30


def saved_answer_for(item: dict, value) -> dict | None:
    """What to remember from the user's answer to this field, or None if
    it shouldn't be reused on other forms."""
    if item["type"] in ("file", "textarea") or is_empty(value):
        return None
    if item["type"] == "boolean":
        return {"labels": ["Yes" if value else "No"]}
    if item["type"] in ("select", "multiselect"):
        values = value if isinstance(value, list) else [value]
        by_value = {o["value"]: o["label"] for o in item.get("options") or []}
        labels = [by_value[v] for v in values if v in by_value]
        return {"labels": labels} if labels and len(labels) == len(values) else None
    return {"text": str(value)}


REUSABLE_KINDS = {"question", "previous_company_contact", "years_experience", "salary", "sponsorship", "work_authorization"}


def fill_answers(
    form: list[dict],
    facts: ApplicantFacts,
    job: JobFacts,
    saved: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Answer what the rules can. Fields left out have no answer yet."""
    saved = saved or {}
    answers: dict[str, dict] = {}
    for item in form:
        kind = classify(item, job)
        result = _from_profile(item, kind, facts, job)
        if (result is None or result.get("value") is None) and kind in REUSABLE_KINDS:
            result = _saved(item, saved) or result

        if result is None and kind == "voluntary":
            value = None
            for option in item.get("options") or []:
                if _DECLINE.search(normalize_label(option["label"])):
                    value = option["value"]
                    break
            if value is not None:
                result = answer([value] if item["type"] == "multiselect" else value, "default",
                                "Voluntary question: declined to answer.")

        if result is None and kind == "marketing":
            value = yes_no(item, False)
            if value is not None:
                result = answer(value, "default", "Declined messages that aren't about this application.")

        if result is None and kind == "preferred_name" and item["required"] and facts.full_name:
            result = answer(facts.full_name.split()[0], "suggested")

        if result is None and kind == "previous_company_contact":
            worked_there = any(normalize_label(job.company) in normalize_label(e) for e in facts.past_employers)
            if "employed" in normalize_label(item["label"]) or "worked" in normalize_label(item["label"]):
                value = yes_no(item, worked_there)
                if value is not None:
                    note = f"{job.company} is {'in' if worked_there else 'not in'} your work history."
                    result = answer(value, "suggested", note)

        if result is None and kind == "years_experience" and facts.years_experience is not None:
            result = _years_answer(item, facts.years_experience)

        if result is None and kind == "salary" and facts.salary_min and item["type"] in ("text", "number"):
            value = facts.salary_min if item["type"] == "number" else f"{facts.salary_min:,} {facts.salary_currency or ''}".strip()
            result = answer(value, "suggested", "Your minimum salary from your profile.")

        if result is None and kind == "agreement":
            result = {"value": None, "source": None, "confirmed": False,
                      "note": "Read this and answer it yourself."}

        if result is None and kind == "cover_letter" and item["required"]:
            result = {"value": None, "source": None, "confirmed": False,
                      "note": "This form requires a cover letter."}

        if result is not None:
            answers[item["key"]] = result
    return answers


def _years_answer(item: dict, years: float) -> dict | None:
    note = "Worked out from the dates in your work history."
    if item["type"] == "number":
        return answer(int(years), "suggested", note)
    if item["type"] == "text":
        return answer(str(int(years)), "suggested", note)
    if item["type"] != "select":
        return None
    for option in item.get("options") or []:
        text = normalize_label(option["label"])
        numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
        if not numbers:
            continue
        if "+" in text or "more" in text or "over" in text:
            low, high = numbers[0], float("inf")
        elif "less" in text or "under" in text:
            low, high = 0.0, numbers[0]
        else:
            low, high = numbers[0], numbers[-1] if len(numbers) > 1 else numbers[0]
        if low <= years < high or (low == high == int(years)):
            return answer(option["value"], "suggested", note)
    return None


def kinds(form: list[dict], job: JobFacts) -> dict[str, str]:
    return {item["key"]: classify(item, job) for item in form}


def needs_attention(item: dict, entry: dict | None) -> bool:
    if entry is None or is_empty(entry.get("value")):
        return bool(item["required"])
    return not entry.get("confirmed")
