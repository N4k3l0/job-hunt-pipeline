from app.workers.discovery_tasks import _one_role_per_user

PM = ["Product Manager", "Senior Product Manager", "Product Owner"]
PM2 = ["product manager", "Junior Product Manager"]
AI = ["AI Engineer", "AI Automation Engineer", "Applied AI Engineer"]
DATA = ["Data Analyst"]


def test_everyone_gets_their_first_role_before_anyone_gets_a_second():
    assert _one_role_per_user([PM, PM2, AI, DATA], limit=5) == [
        "product manager",  # shared by the two PM users: searched once
        "ai engineer",
        "data analyst",
        "senior product manager",
        "junior product manager",
    ]


def test_more_users_than_searches_rotates_who_goes_first():
    users = [["designer"], ["recruiter"], ["nurse"]]
    assert _one_role_per_user(users, limit=2, start=0) == ["designer", "recruiter"]
    assert _one_role_per_user(users, limit=2, start=1) == ["recruiter", "nurse"]
    assert _one_role_per_user(users, limit=2, start=5) == ["nurse", "designer"]


def test_users_without_roles_are_skipped():
    assert _one_role_per_user([[], [" ", "x"], ["ML Engineer "]], limit=5) == ["ml engineer"]
    assert _one_role_per_user([[], []], limit=5) == []
