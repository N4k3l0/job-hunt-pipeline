"""Version 3 scoring gives no points for what isn't known and keeps jobs
that match neither the candidate's roles nor their skills out of the inbox."""

import pytest

from app.services.scoring.scorer import IRRELEVANT_MAX_SCORE, compute_job_score

PROFILE = {
    "target_roles": ["AI Engineer"],
    "search_keywords": [],
    "preferred_countries": [],
    "visa_statuses": {},
    "remote_preference": "any",
    "salary_min": None,
    "salary_max": None,
    "skills": [{"skill_name": s} for s in ["Python", "LangChain", "RAG", "FastAPI", "SQL"]],
    "work_history": [
        {"title": "Senior AI Engineer", "start_date": "2017-01-01", "end_date": None,
         "skills": [], "domain_tags": []},
    ],
}


def _job(title, skills, seniority=None, remote_type="full_remote", description=""):
    return (
        {"title": title, "company": "Co", "country": None, "remote_type": remote_type,
         "seniority": seniority, "raw_description": description},
        {"skills": skills, "nice_to_have": [], "requirements": [], "keywords": [],
         "sponsorship_available": None, "years_experience_min": None},
    )


def _score(job, profile=PROFILE, version=3):
    return compute_job_score(*job, profile, version=version)


def test_version_2_is_unchanged_by_default():
    job = _job("Senior AI Engineer", ["Python", "RAG"], seniority="senior")
    assert compute_job_score(*job, PROFILE)["score_version"] == 2
    assert compute_job_score(*job, PROFILE) == _score(job, version=2)


def test_a_full_match_still_scores_top():
    result = _score(_job("Senior AI Engineer", ["Python", "RAG", "LangChain"], seniority="senior"))
    assert result["overall_fit"] >= 90
    assert result["score_version"] == 3
    # Remote "any" and no industries on the profile: those parts aren't counted.
    assert result["reasoning"]["counted"] == ["seniority", "skills", "title"]


def test_an_unstated_level_earns_nothing():
    known = _score(_job("AI Engineer", ["Python", "RAG"], seniority="senior"))
    unknown = _score(_job("AI Engineer", ["Python", "RAG"]))
    assert unknown["seniority_score"] == 0
    assert unknown["overall_fit"] < known["overall_fit"] - 20
    # Version 2 gave the unknown level a middle score.
    assert _score(_job("AI Engineer", ["Python", "RAG"]), version=2)["seniority_score"] > 8


def test_a_level_two_steps_away_scores_low():
    near = _score(_job("AI Engineer", ["Python"], seniority="lead"))
    far = _score(_job("AI Engineer", ["Python"], seniority="entry"))
    assert far["seniority_score"] < near["seniority_score"]
    assert far["seniority_score"] <= 3


def test_remote_policy_counts_only_with_a_preference():
    profile = {**PROFILE, "remote_preference": "full_remote"}
    remote = _score(_job("AI Engineer", ["Python"], seniority="senior"), profile)
    unstated = _score(_job("AI Engineer", ["Python"], seniority="senior", remote_type=None), profile)
    assert "remote" in remote["reasoning"]["counted"]
    assert unstated["overall_fit"] < remote["overall_fit"]


@pytest.mark.parametrize("version,in_inbox", [(2, True), (3, False)])
def test_no_role_or_skill_match_stays_out_of_the_inbox(version, in_inbox):
    # A near miss on both: a related title and two of five skills, with the
    # level unknown.
    job = _job("Machine Learning Engineer", ["Python", "SQL", "Spark", "Airflow", "dbt"],
               description="Python SQL")
    result = _score(job, version=version)
    assert (result["overall_fit"] >= 50) is in_inbox, result["overall_fit"]
    if version == 3:
        assert result["overall_fit"] <= IRRELEVANT_MAX_SCORE
        assert result["reasoning"]["role_or_skill_match"] is False


def test_a_skills_match_alone_is_enough_to_be_relevant():
    result = _score(_job("Platform Developer", ["Python", "LangChain", "RAG"], seniority="senior"))
    assert result["reasoning"]["role_or_skill_match"] is True
    assert result["overall_fit"] > IRRELEVANT_MAX_SCORE


def test_an_empty_profile_does_not_crash():
    empty = {"target_roles": [], "skills": [], "work_history": [], "remote_preference": "any"}
    result = _score(_job("Anything", []), empty)
    assert result["overall_fit"] == 0
