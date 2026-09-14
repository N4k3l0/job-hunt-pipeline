"""What the app fills in on its own, and what it leaves for the user."""

from app.services.auto_apply.answers import (
    ApplicantFacts,
    JobFacts,
    choose_option,
    classify,
    countries_in,
    fill_answers,
    needs_attention,
    question_key,
    saved_answer_for,
)

YES_NO = [{"label": "Yes", "value": "1"}, {"label": "No", "value": "0"}]


def field(key, label, type_="text", required=True, options=None, group="application", description=None):
    return {"key": key, "label": label, "type": type_, "required": required, "options": options,
            "description": description, "group": group}


def facts(**overrides):
    base = dict(
        full_name="Ada Obi", email="ada@example.com", phone="+234 800 000 0000", location="Lagos, Nigeria",
        home_country="NG", visa_statuses={}, links={"linkedin": "https://linkedin.com/in/ada"},
        current_company="Acme", current_title="Product Manager", past_employers=["Acme", "Globex Ltd"],
        years_experience=6.5, salary_min=90000, salary_currency="USD", has_resume=True,
    )
    base.update(overrides)
    return ApplicantFacts(**base)


def fill(form, applicant=None, job=None, saved=None):
    return fill_answers(form, applicant or facts(), job or JobFacts("Stripe", "US"), saved)


def test_contact_details_come_from_the_profile():
    form = [
        field("first_name", "First Name"), field("last_name", "Last Name"), field("email", "Email", "email"),
        field("phone", "Phone", "phone"), field("resume", "Resume/CV", "file"),
        field("q1", "LinkedIn Profile", required=False), field("q2", "Who is your current or previous employer?"),
        field("q3", "What is your current or previous job title?"), field("location", "Location", "location"),
    ]
    answers = fill(form)
    assert {k: a["value"] for k, a in answers.items()} == {
        "first_name": "Ada", "last_name": "Obi", "email": "ada@example.com", "phone": "+234 800 000 0000",
        "resume": "resume", "q1": "https://linkedin.com/in/ada", "q2": "Acme", "q3": "Product Manager",
        "location": "Lagos, Nigeria",
    }
    assert all(a["confirmed"] and a["source"] == "profile" for a in answers.values())
    assert not any(needs_attention(f, answers.get(f["key"])) for f in form)


def test_missing_contact_details_are_asked_for():
    form = [field("phone", "Phone", "phone"), field("resume", "Resume", "file"), field("x", "GitHub URL", "url", required=False)]
    answers = fill(form, facts(phone=None, has_resume=False, links={}))
    assert needs_attention(form[0], answers["phone"]) and "profile" in answers["phone"]["note"]
    assert needs_attention(form[1], answers["resume"])
    assert not needs_attention(form[2], answers.get("x"))  # optional and unknown: left blank


def test_country_of_residence_picks_the_country_or_other():
    listed = field("c", "Please select the country where you currently reside.", "select",
                   options=[{"label": "UK", "value": "7"}, {"label": "Nigeria", "value": "8"}, {"label": "Other", "value": "9"}])
    unlisted = field("c", "Please select the country where you currently reside.", "select",
                     options=[{"label": "UK", "value": "7"}, {"label": "Other", "value": "9"}])
    assert fill([listed])["c"]["value"] == "8"
    assert fill([unlisted])["c"]["value"] == "9"
    assert fill([listed], facts(home_country="GB"))["c"]["value"] == "7"


def test_work_rights_answers_only_when_the_profile_settles_them():
    auth = field("a", "Are you authorized to work in the country where the job is located?", "boolean")
    sponsor = field("s", "Will you now or in the future require visa sponsorship to work in the United States?", "select", options=YES_NO)

    # Home country: authorized, no sponsorship.
    answers = fill([auth, sponsor], facts(home_country="US"), JobFacts("Stripe", "US"))
    assert answers["a"]["value"] is True and answers["a"]["confirmed"]
    assert answers["s"]["value"] == "0" and answers["s"]["confirmed"]

    # Needs sponsorship there: not authorized, needs sponsorship.
    answers = fill([auth, sponsor], facts(visa_statuses={"US": "need_sponsorship"}), JobFacts("Stripe", "US"))
    assert answers["a"]["value"] is False
    assert answers["s"]["value"] == "1"

    # Nothing in the profile about the US: the user answers.
    answers = fill([auth, sponsor], facts(), JobFacts("Stripe", "US"))
    assert answers["a"]["value"] is None and needs_attention(auth, answers["a"])
    assert answers["s"]["value"] is None and needs_attention(sponsor, answers["s"])

    # A work visa today doesn't say whether sponsorship is needed later.
    answers = fill([sponsor], facts(visa_statuses={"US": "work_visa"}))
    assert answers["s"]["value"] is None

    # The job's country is unknown: nothing to go on.
    answers = fill([auth], facts(home_country="US"), JobFacts("Stripe", None))
    assert needs_attention(auth, answers.get("a"))


def test_agreements_are_always_left_to_the_user():
    form = [
        field("arb", "Applicant Arbitration Agreement Acknowledgement", "multiselect",
              options=[{"label": "I acknowledge that I have read the Arbitration Agreement", "value": "x"}]),
        field("ai", "AI Policy for Application", "select", options=YES_NO),
        field("gdpr", "GDPR: I consent to the processing of my personal data", "boolean"),
        field("req_marketing", "I consent to being contacted about future opportunities", "boolean"),
    ]
    answers = fill(form)
    for f in form:
        assert classify(f, JobFacts("Stripe")) == "agreement", f["label"]
        assert answers[f["key"]]["value"] is None
        assert needs_attention(f, answers[f["key"]])


def test_voluntary_questions_are_declined_when_possible():
    form = [
        field("gender", "Gender", "select", required=False, group="voluntary",
              options=[{"label": "Male", "value": "1"}, {"label": "Decline To Self Identify", "value": "3"}]),
        field("race", "What is your race?", "multiselect", required=False,
              options=[{"label": "Asian", "value": "a"}, {"label": "I prefer not to answer", "value": "p"}]),
        field("vet", "Veteran status", "select", required=False, options=[{"label": "Yes", "value": "y"}]),
    ]
    answers = fill(form)
    assert answers["gender"]["value"] == "3" and answers["gender"]["confirmed"]
    assert answers["race"]["value"] == ["p"]
    assert "vet" not in answers and not needs_attention(form[2], None)


def test_marketing_messages_are_declined():
    form = [
        field("consent[marketing]", "Spotify may contact me about future job opportunities.", "boolean", required=False),
        field("wa", "Do you opt-in to receive WhatsApp messages from Stripe Recruiting?", "select", options=YES_NO),
    ]
    answers = fill(form)
    assert answers["consent[marketing]"]["value"] is False and answers["consent[marketing]"]["confirmed"]
    assert answers["wa"]["value"] == "0" and answers["wa"]["confirmed"]


def test_previous_employment_is_suggested_not_confirmed():
    question = field("p", "Have you ever been employed by Stripe or a Stripe affiliate?", "select", options=YES_NO)
    answers = fill([question])
    assert answers["p"]["value"] == "0" and not answers["p"]["confirmed"]
    assert needs_attention(question, answers["p"])
    # "Globex Ltd" is in the work history.
    worked = field("p", "Have you ever worked at Globex?", "select", options=YES_NO)
    assert fill([worked], job=JobFacts("Globex", "US"))["p"]["value"] == "1"


def test_saved_answers_are_reused():
    question = field("q", "How did you hear about this job?", "select",
                     options=[{"label": "LinkedIn", "value": "11"}, {"label": "Job board", "value": "12"}])
    same_question_elsewhere = field("other", "How did you hear about this job?", "select",
                                    options=[{"label": "Job Board", "value": "b"}, {"label": "Referral", "value": "r"}])
    stored = saved_answer_for(question, "12")
    assert stored == {"labels": ["Job board"]}

    saved = {question_key(question): {**stored, "fresh": True}}
    answers = fill([same_question_elsewhere], saved=saved)
    assert answers["other"]["value"] == "b" and answers["other"]["source"] == "saved"
    assert not needs_attention(same_question_elsewhere, answers["other"])

    stale = {question_key(question): {**stored, "fresh": False}}
    answers = fill([same_question_elsewhere], saved=stale)
    assert answers["other"]["value"] == "b" and not answers["other"]["confirmed"]

    # A saved choice that isn't offered on this form isn't used.
    no_match = field("x", "How did you hear about this job?", "select", options=[{"label": "Referral", "value": "r"}])
    assert "x" not in fill([no_match], saved=saved)


def test_long_answers_and_files_are_not_remembered():
    assert saved_answer_for(field("w", "Why Stripe?", "textarea"), "Because...") is None
    assert saved_answer_for(field("r", "Resume", "file"), "resume") is None
    assert saved_answer_for(field("b", "Can you start in May?", "boolean"), False) == {"labels": ["No"]}


def test_years_of_experience_picks_the_matching_range():
    bands = field("y", "Years of experience", "select",
                  options=[{"label": "0-2", "value": "a"}, {"label": "2-5", "value": "b"}, {"label": "5-8", "value": "c"},
                           {"label": "8+", "value": "d"}])
    answers = fill([bands])
    assert answers["y"]["value"] == "c" and not answers["y"]["confirmed"]
    assert fill([bands], facts(years_experience=9))["y"]["value"] == "d"
    # Experience with a particular skill isn't worked out from dates.
    skill = field("s", "How many years of professional Android experience do you have?", "select", options=bands["options"])
    assert "s" not in fill([skill])


def test_helpers():
    assert choose_option({"options": [{"label": "None", "value": "n"}, {"label": "No, thanks", "value": "x"}]}, "no") == "x"
    assert countries_in("Are you authorized to work in the US?") == ["US"]
    assert countries_in("Tell us about yourself") == []
    assert countries_in("Can you work in the United Kingdom or Ireland?") == ["IE", "GB"]
