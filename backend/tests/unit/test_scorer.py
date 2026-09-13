import json
from decimal import Decimal

from app.services.scoring.scorer import compute_job_score


class ArrayLike(list):
    """Stand-in for the numpy arrays pgvector < 0.5 returned."""

    def __bool__(self):
        raise ValueError("The truth value of an array with more than one element is ambiguous")


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


def test_array_like_embeddings_use_semantic_mode():
    vec = ArrayLike(Decimal(i + 1) / 512 for i in range(512))
    result = compute_job_score(
        JOB,
        {**ENTITIES, "embedding": vec},
        {**PROFILE, "embedding": vec},
    )
    assert result["reasoning"]["scoring_mode"] == "semantic"
    assert result["semantic_score"] == 1.0
    assert 0 <= result["overall_fit"] <= 100
    # reasoning is stored as JSONB, so it must serialize.
    json.dumps(result["reasoning"])


def test_list_embeddings_use_semantic_mode():
    vec = [0.1] * 512
    result = compute_job_score(JOB, {**ENTITIES, "embedding": vec}, {**PROFILE, "embedding": vec})
    assert result["reasoning"]["scoring_mode"] == "semantic"


def test_missing_embedding_falls_back_to_rules():
    result = compute_job_score(JOB, ENTITIES, {**PROFILE, "embedding": None})
    assert result["reasoning"]["scoring_mode"] == "rule-based"
    assert result["semantic_score"] == 0.0
    assert result["overall_fit"] > 0


def test_worldwide_preference_is_not_treated_as_a_country():
    worldwide = compute_job_score(JOB, ENTITIES, {**PROFILE, "preferred_countries": ["WW"]})
    no_pref = compute_job_score(JOB, ENTITIES, {**PROFILE, "preferred_countries": []})
    assert worldwide["geo_score"] == no_pref["geo_score"]
