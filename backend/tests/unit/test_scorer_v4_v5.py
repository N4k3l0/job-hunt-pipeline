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


def test_version_5_is_live():
    assert SCORE_VERSION == 5 and PROPOSED_SCORE_VERSION == 5
    assert set(KNOWN_VERSIONS) == {2, 3, 4, 5}
    job = _job("Senior AI Engineer", ["Python", "RAG"], seniority="senior")
    assert compute_job_score(*job, PROFILE) == _score(job, 5)
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
