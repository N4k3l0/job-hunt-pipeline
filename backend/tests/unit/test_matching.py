import pytest

from app.services.scoring.matching import (
    domain_match,
    seniority_match,
    skill_match,
    title_match,
    title_similarity,
)


@pytest.mark.parametrize(
    "role, job_title, low",
    [
        ("Registered Nurse", "Senior Registered Nurse - ICU", 0.9),
        ("Accountant", "Staff Accountant", 0.9),
        ("Product Manager", "Senior Product Manager, Payments", 0.8),
        ("Marketing Manager", "Marketing Lead", 0.8),
        ("Software Engineer", "Backend Software Engineer II", 0.8),
        ("Graphic Designer", "Graphic Design Specialist", 0.6),
        ("Medical Assistant", "Medical Assistant (Part-Time)", 0.9),
    ],
)
def test_related_titles_score_high(role, job_title, low):
    assert title_similarity(role, job_title) >= low


@pytest.mark.parametrize(
    "role, job_title",
    [
        ("Registered Nurse", "Software Engineer"),
        ("Accountant", "Product Designer"),
        ("Product Manager", "Data Engineer"),
    ],
)
def test_unrelated_titles_score_low(role, job_title):
    assert title_similarity(role, job_title) <= 0.4


def test_titles_sharing_only_the_generic_word_stay_below_a_real_match():
    partial = title_similarity("Medical Assistant", "Executive Assistant to the CEO")
    real = title_similarity("Medical Assistant", "Medical Assistant (Part-Time)")
    assert partial <= 0.5 < real


def test_title_match_uses_recent_titles_when_no_target_roles():
    score, matched = title_match("Staff Accountant", [], ["Accountant", "Bookkeeper"])
    assert score >= 0.7
    assert matched == "Accountant"


def test_interests_count_as_secondary_roles():
    score, matched = title_match("Fintech Product Manager", ["Accountant"], None, interests=["fintech product manager"])
    assert matched == "fintech product manager"
    assert 0.8 <= score <= 0.9


def test_title_match_is_neutral_without_any_role_information():
    assert title_match("Anything", None, None) == (0.5, None)


def test_skill_match_uses_extracted_skills():
    score, matched, missing = skill_match(
        ["IFRS", "Excel", "Month-end close", "SAP"],
        "",
        ["Excel", "IFRS reporting", "NetSuite"],
    )
    assert set(matched) == {"ifrs", "excel"}
    assert "sap" in missing
    assert 0.3 < score < 0.8


def test_skill_match_falls_back_to_description_mentions():
    score, matched, _ = skill_match(
        [],
        "You will use Figma and Adobe Illustrator daily, and some After Effects.",
        ["Figma", "Adobe Illustrator", "Photoshop"],
    )
    assert set(matched) == {"figma", "adobe illustrator"}
    assert score > 0


def test_skill_match_splits_parenthetical_aliases():
    _, matched, _ = skill_match(["n8n"], "", ["Workflow Automation (n8n)"])
    assert matched == ["n8n"]


def test_short_skills_do_not_match_inside_words():
    # "go" must not match "Go-to-market" style text via the description.
    score, matched, _ = skill_match([], "Own our go-to-market plan.", ["Go"])
    assert matched == []
    assert score == 0


def test_seniority_match_rewards_same_level():
    history = [{"title": "Senior Nurse", "start_date": "2016-01-01", "end_date": None}]
    same, _ = seniority_match("senior", "Senior Nurse", None, history)
    far, _ = seniority_match("entry", "Nurse Graduate Program", None, history)
    assert same == 1.0
    assert far < same


def test_seniority_match_penalizes_missing_required_years():
    history = [{"title": "Accountant", "start_date": "2023-01-01", "end_date": None}]
    score, detail = seniority_match(None, "Accountant", 8, history)
    assert score <= 0.4
    assert detail["candidate_years"] < 8


def test_candidate_years_counts_overlapping_jobs_once():
    from datetime import date
    from app.services.scoring.matching import candidate_years

    history = [
        {"start_date": "2020-01-01", "end_date": "2022-01-01"},
        {"start_date": "2021-01-01", "end_date": "2023-01-01"},  # overlaps the first
        {"start_date": "2024-01-01", "end_date": "2025-01-01"},
    ]
    assert candidate_years(history, today=date(2026, 1, 1)) == 4.0


def test_long_experience_alone_does_not_make_someone_a_director():
    history = [{"title": "Registered Nurse", "start_date": "2008-01-01", "end_date": None}]
    _, detail = seniority_match("senior", "Senior Registered Nurse", None, history)
    assert detail["candidate_level"] == "senior"


def test_seniority_is_neutral_without_work_history():
    score, _ = seniority_match("senior", "Senior Engineer", None, [])
    assert score == 0.55


def test_domain_match():
    score, hits = domain_match("A pediatrics clinic hiring nurses", ["Pediatrics", "Oncology"])
    assert hits == ["pediatrics"]
    assert score == 0.5
    assert domain_match("anything", []) == (0.5, [])
