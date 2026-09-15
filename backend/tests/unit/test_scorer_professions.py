"""The scorer should rank a candidate's own kind of job above unrelated
jobs, whatever the profession."""

import pytest

from app.services.scoring.scorer import PROPOSED_SCORE_VERSION, SCORE_VERSION, compute_job_score


def _profile(roles, skills, titles, domain_tags=None, remote="any"):
    return {
        "target_roles": roles,
        "preferred_countries": [],
        "visa_statuses": {},
        "remote_preference": remote,
        "salary_min": None,
        "salary_max": None,
        "skills": [{"skill_name": s} for s in skills],
        "work_history": [
            {"title": t, "start_date": "2017-03-01", "end_date": None if i == 0 else "2020-01-01",
             "skills": [], "domain_tags": domain_tags or []}
            for i, t in enumerate(titles)
        ],
        }


def _job(title, skills, description="", seniority=None, remote_type="onsite"):
    job_data = {
        "title": title, "company": "Co", "country": "GB", "remote_type": remote_type,
        "seniority": seniority, "raw_description": description,
    }
    entities = {"skills": skills, "nice_to_have": [], "requirements": [], "keywords": [],
                "sponsorship_available": None, "years_experience_min": None}
    return job_data, entities


PROFILES = {
    "nurse": _profile(
        ["Registered Nurse"], ["Patient care", "IV therapy", "BLS", "EPIC"],
        ["Registered Nurse", "Nursing Assistant"], ["Healthcare"],
    ),
    "accountant": _profile(
        ["Accountant", "Financial Analyst"], ["IFRS", "Excel", "Month-end close", "Xero"],
        ["Accountant", "Accounts Assistant"], ["Fintech"],
    ),
    "designer": _profile(
        ["Product Designer"], ["Figma", "User research", "Prototyping", "Design systems"],
        ["Product Designer", "UI Designer"],
    ),
}

JOBS = {
    "nurse": _job("Senior Registered Nurse - Surgical Ward", ["BLS", "Patient care", "EPIC", "Wound care"]),
    "accountant": _job("Management Accountant", ["IFRS", "Excel", "Month-end close", "Budgeting"]),
    "designer": _job("Senior Product Designer", ["Figma", "Prototyping", "User research"], remote_type="full_remote"),
}


@pytest.mark.parametrize("version", [SCORE_VERSION, PROPOSED_SCORE_VERSION])
@pytest.mark.parametrize("profession", sorted(PROFILES))
def test_own_profession_ranks_first(profession, version):
    profile = PROFILES[profession]
    scores = {
        name: compute_job_score(job_data, entities, profile, version=version)["overall_fit"]
        for name, (job_data, entities) in JOBS.items()
    }
    own = scores.pop(profession)
    # Version 3 gives nothing for the level the accountant job doesn't state.
    assert own >= (65 if version < 3 else 50), (profession, own)
    assert all(own - other >= 25 for other in scores.values()), (profession, own, scores)


def test_output_shape_matches_job_score_columns():
    job_data, entities = JOBS["nurse"]
    result = compute_job_score(job_data, entities, PROFILES["nurse"])
    assert result["role_path"] == "general"
    assert result["score_version"] == SCORE_VERSION
    assert 0 <= result["title_score"] <= 20
    assert 0 <= result["skill_score"] <= 25
    assert 0 <= result["seniority_score"] <= 15
    assert 0 <= result["industry_score"] <= 10
    assert result["reasoning"]["matched_role"] == "Registered Nurse"
    assert "bls" in result["reasoning"]["skills_matched"]
    assert "wound care" in result["reasoning"]["skills_missing"]
