"""Versions 4 and 5, the candidates to replace version 2.

Version 4 counts a part of the score only when both sides know something
about it, so nothing earns points for being unknown. Version 5 is version 4
with job titles compared by their specific words."""

from app.services.scoring.matching import title_match
from app.services.scoring.scorer import (
    KNOWN_VERSIONS, PROPOSED_SCORE_VERSION, SCORE_VERSION, WEIGHTS, compute_job_score,
)

PROFILE = {
    "target_roles": ["AI Engineer"],
    "search_keywords": [],
    "preferred_countries": [],
    "visa_statuses": {},
    "remote_preference": "any",
    "salary_min": None,
    "salary_max": None,
    "skills": [{"skill_name": s} for s in ["Python", "LangChain", "RAG", "FastAPI", "SQL", "Verilog"]],
    "work_history": [
        {"title": "Senior AI Engineer", "start_date": "2017-01-01", "end_date": None,
         "skills": [], "domain_tags": []},
    ],
}


def _job(title, skills, seniority=None, remote_type="full_remote"):
    return (
        {"title": title, "company": "Co", "country": None, "remote_type": remote_type,
         "seniority": seniority, "raw_description": ""},
        {"skills": skills, "nice_to_have": [], "requirements": [], "keywords": [],
         "sponsorship_available": None, "years_experience_min": None},
    )


def _score(job, version, profile=PROFILE):
    return compute_job_score(*job, profile, version=version)


def test_version_6_is_live():
    assert SCORE_VERSION == 6 and PROPOSED_SCORE_VERSION == 6
    assert set(KNOWN_VERSIONS) == {2, 3, 4, 5, 6}
    job = _job("Senior AI Engineer", ["Python", "RAG"], seniority="senior")
    assert compute_job_score(*job, PROFILE) == _score(job, 6)
    # Version 2 titles still give half marks for sharing the role noun.
    assert title_match("FPGA Engineer", ["AI Engineer"])[0] == 0.5


def test_a_company_name_in_the_title_is_not_the_job():
    """Seen in the ratings: "Head of Operations @ Koast.ai" scored 84 for an
    AI engineer because "ai" from the company name matched."""
    assert title_match("Head of Operations @ Koast.ai", ["AI Engineer"], weighted=True)[0] == 0.0
    assert title_match("AI Engineer @ Acme", ["AI Engineer"], weighted=True)[0] == 1.0


def test_one_shared_skill_tag_no_longer_counts():
    fpga = _job("FPGA Engineer", ["Verilog"])
    v4 = _score(fpga, 4)
    assert "skills" not in v4["reasoning"]["counted"]


def test_nothing_earns_points_for_being_unknown():
    """No level stated, no remote preference, no industries on the profile:
    those parts aren't counted at all, so only the title decides."""
    result = _score(_job("AI Engineer", ["Python"]), 4)
    assert result["reasoning"]["counted"] == ["title"]
    assert result["overall_fit"] == round(100 * result["title_score"] / 20, 1)


def test_what_is_known_is_weighted_as_before():
    result = _score(_job("AI Engineer", ["Python", "RAG", "LangChain"], seniority="senior"), 4)
    assert result["reasoning"]["counted"] == ["seniority", "skills", "title"]
    counted_weight = WEIGHTS["title"] + WEIGHTS["skills"] + WEIGHTS["seniority"]
    assert result["overall_fit"] >= 90 and abs(counted_weight - 0.85) < 1e-9


def test_a_remote_preference_counts_when_the_job_states_its_policy():
    wants_remote = {**PROFILE, "remote_preference": "full_remote"}
    stated = _score(_job("AI Engineer", ["Python"]), 4, profile=wants_remote)
    unstated = _score(_job("AI Engineer", ["Python"], remote_type=None), 4, profile=wants_remote)
    assert "remote" in stated["reasoning"]["counted"]
    assert "remote" not in unstated["reasoning"]["counted"]


def test_version_5_compares_titles_by_their_specific_words():
    """Sharing only "Engineer" is not a title match."""
    fpga = _job("FPGA Engineer", ["Verilog"])
    assert _score(fpga, 5)["overall_fit"] < _score(fpga, 4)["overall_fit"] - 20
    assert _score(fpga, 5)["overall_fit"] < 30
    assert title_match("Applied AI Engineer", ["AI Engineer"], weighted=True)[0] >= 0.85
    assert title_match("Senior AI Engineer", ["AI Engineer"], weighted=True)[0] == 1.0


AUTOMATION_PROFILE = {
    **PROFILE,
    "target_roles": ["AI Engineer", "Automation Engineer"],
    "skills": [{"skill_name": s} for s in ["Python", "LangChain", "RAG", "FastAPI", "SQL", "n8n", "LLM"]],
}

FACTORY = (
    "We are looking for an Automation Engineer to support our manufacturing plant. You will design, program "
    "and troubleshoot PLC systems (Allen-Bradley, Siemens S7), HMI screens and SCADA, commission conveyors "
    "and robotic cells, and work with maintenance technicians on the production floor to reduce downtime. "
    "Experience with ladder logic, motor controls, P&IDs and electrical schematics is required."
)
AI_JOB = (
    "Join our team as an AI Engineer. You will build LLM applications in Python with LangChain and RAG, "
    "serve them with FastAPI, automate workflows with n8n, and work with SQL data. You will take features "
    "from prototype to production with our customers and keep improving them as you learn what works."
)


def _described(title, description):
    return (
        {"title": title, "company": "Co", "country": None, "remote_type": "full_remote",
         "seniority": None, "raw_description": description},
        {"skills": [], "nice_to_have": [], "requirements": [], "keywords": [],
         "sponsorship_available": None, "years_experience_min": None},
    )


def test_version_6_reads_the_description_when_skills_arent_listed():
    """Seen on 2026-10-14: factory "Automation Engineer" jobs scored 84 to
    86 for an AI engineer on their title alone."""
    factory = _described("Automation Engineer", FACTORY)
    v5, v6 = _score(factory, 5, AUTOMATION_PROFILE), _score(factory, 6, AUTOMATION_PROFILE)
    assert v5["overall_fit"] >= 80 and "skills" not in v5["reasoning"]["counted"]
    assert v6["overall_fit"] < 70 and "skills" in v6["reasoning"]["counted"]

    # A job that does want their skills keeps its place.
    ai = _described("AI Engineer", AI_JOB)
    assert _score(ai, 6, AUTOMATION_PROFILE)["overall_fit"] >= 85
    assert _score(ai, 6, AUTOMATION_PROFILE)["reasoning"]["skills_matched"]


def test_version_6_changes_nothing_without_a_real_description():
    for job in (_described("Automation Engineer", "Automation Engineer, Ohio."), _job("AI Engineer", ["Python", "RAG", "SQL"])):
        assert _score(job, 6, AUTOMATION_PROFILE)["overall_fit"] == _score(job, 5, AUTOMATION_PROFILE)["overall_fit"]
