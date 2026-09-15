from app.services.scoring.scorer import compute_job_score


JOB = {
    "title": "Senior Product Manager",
    "company": "Acme",
    "country": "NL",
    "remote_type": "full_remote",
    "seniority": "senior",
    "raw_description": "Own the roadmap for our B2B SaaS platform.",
}
ENTITIES = {
    "skills": ["roadmap", "sql", "stakeholder management"],
    "requirements": [],
    "keywords": [],
    "sponsorship_available": None,
}
PROFILE = {
    "target_roles": ["Product Manager"],
    "preferred_countries": ["NL"],
    "visa_statuses": {},
    "remote_preference": "full_remote",
    "salary_min": None,
    "salary_max": None,
    "skills": [{"skill_name": "roadmap"}, {"skill_name": "sql"}],
    "work_history": [
        {"title": "Product Manager", "start_date": "2016-01-01", "end_date": None, "skills": []},
    ],
}


def test_worldwide_preference_is_not_treated_as_a_country():
    worldwide = compute_job_score(JOB, ENTITIES, {**PROFILE, "preferred_countries": ["WW"]})
    no_pref = compute_job_score(JOB, ENTITIES, {**PROFILE, "preferred_countries": []})
    assert worldwide["geo_score"] == no_pref["geo_score"]
