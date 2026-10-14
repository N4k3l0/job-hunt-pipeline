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
    assert SCORE_VERSION == 6 and PROPOSED_SCORE_VERSION == 7
    assert set(KNOWN_VERSIONS) == {2, 3, 4, 5, 6, 7, 8}
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
    "from prototype to production with our customers and keep improving them as you learn what works. "
    "You will pair with designers and product managers, and share what you learn with the wider team."
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
    ai = _score(_described("AI Engineer", AI_JOB), 6, AUTOMATION_PROFILE)
    assert len(AI_JOB) >= 300 and "skills" in ai["reasoning"]["counted"]
    assert ai["overall_fit"] >= 85 and ai["reasoning"]["skills_matched"]


def test_version_6_changes_nothing_without_a_real_description():
    for job in (_described("Automation Engineer", "Automation Engineer, Ohio."), _job("AI Engineer", ["Python", "RAG", "SQL"])):
        assert _score(job, 6, AUTOMATION_PROFILE)["overall_fit"] == _score(job, 5, AUTOMATION_PROFILE)["overall_fit"]


NIGERIA = {
    **AUTOMATION_PROFILE,
    "home_country": "NG",
    "visa_statuses": {"US": "need_sponsorship", "GB": "need_sponsorship"},
    "skills": AUTOMATION_PROFILE["skills"] + [{"skill_name": s} for s in ("Communication", "Slack", "Google Workspace")],
}


def _placed(country, remote_type, sponsorship=None, description=AI_JOB):
    job_data, entities = _described("AI Engineer", description)
    return {**job_data, "country": country, "remote_type": remote_type}, {**entities, "sponsorship_available": sponsorship}


def test_version_7_leaves_out_skills_every_job_mentions():
    """Seen on 2026-10-14: "communication", "slack" and "google workspace"
    were 3 of the 5 skills a job matched on."""
    office = (
        "You will keep our office running: answer the phones, book travel and order supplies. Strong "
        "communication and teamwork matter here, and we use Slack and Google Workspace every day. You will "
        "also look after visitors, keep the calendar and help the team with whatever comes up each week."
    )
    job = _described("Office Coordinator", office)
    v6, v7 = _score(job, 6, NIGERIA), _score(job, 7, NIGERIA)
    assert {"communication", "slack", "google workspace"} <= set(v6["reasoning"]["skills_matched"])
    assert v7["reasoning"]["skills_matched"] == []
    assert v7["skill_score"] < v6["skill_score"]


def test_version_8_scores_jobs_needing_a_sponsor_a_little_lower():
    remote = _score(_placed(None, "full_remote"), 8, NIGERIA)
    home = _score(_placed("NG", "onsite"), 8, NIGERIA)
    sponsors = _score(_placed("US", "onsite", sponsorship=True), 8, NIGERIA)
    unknown = _score(_placed("US", "onsite"), 8, NIGERIA)
    assert remote["overall_fit"] == home["overall_fit"] > sponsors["overall_fit"] > unknown["overall_fit"]
    # A little: a few points, not a different league.
    assert 2 <= remote["overall_fit"] - unknown["overall_fit"] <= 6
    assert unknown["reasoning"]["work_rights"] == "needs_sponsor"
    # Versions 6 and 7 don't look at work rights.
    for version in (6, 7):
        places = ((None, "full_remote"), ("US", "onsite"))
        assert len({_score(_placed(c, r), version, NIGERIA)["overall_fit"] for c, r in places}) == 1
    # Without any work rights on the profile, nothing changes.
    plain = {**NIGERIA, "home_country": None, "visa_statuses": {}}
    assert _score(_placed("US", "onsite"), 8, plain)["overall_fit"] == _score(_placed(None, "full_remote"), 8, plain)["overall_fit"]


def test_the_level_the_user_chose_is_theirs():
    """The user said: "mid, not beginner, not senior"."""
    founder = {**NIGERIA, "work_history": [
        {"title": "Founder", "start_date": "2024-01-01", "end_date": None, "skills": [], "domain_tags": []},
    ]}
    senior_job = _job("Senior AI Engineer", ["Python", "RAG", "SQL"], seniority="senior")
    chosen = _score(senior_job, 6, {**founder, "level": "mid"})
    assert chosen["reasoning"]["candidate_level"] == "mid"
    assert chosen["seniority_score"] == 0.7 * 15  # one step up
