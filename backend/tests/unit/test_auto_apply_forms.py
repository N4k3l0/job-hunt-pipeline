"""Recognising supported hiring systems and reading their forms. The
sample payloads mirror what Greenhouse, Ashby and Lever returned for real
postings in September 2026, trimmed to the parts the readers use."""

import html
import json

import pytest

from app.services.auto_apply.ats import detect_ats
from app.services.auto_apply.forms import FormUnavailable, parse_ashby, parse_greenhouse, parse_lever


@pytest.mark.parametrize("url, expected", [
    ("https://job-boards.greenhouse.io/anthropic/jobs/4461450008", ("greenhouse", "anthropic", "4461450008", False)),
    ("https://boards.greenhouse.io/figma/jobs/5426468004?gh_jid=5426468004", ("greenhouse", "figma", "5426468004", False)),
    ("https://job-boards.eu.greenhouse.io/acme/jobs/123", ("greenhouse", "acme", "123", True)),
    ("https://boards.greenhouse.io/embed/job_app?for=stripe&token=8172510", ("greenhouse", "stripe", "8172510", False)),
    ("https://stripe.com/careers/listing/abuse-investigator/8172510?gh_jid=8172510", ("greenhouse", None, "8172510", False)),
    ("https://jobs.lever.co/spotify/2193DB3F-77c5-43b8-b030-8f92c9882bf1/apply", ("lever", "spotify", "2193db3f-77c5-43b8-b030-8f92c9882bf1", False)),
    ("https://jobs.eu.lever.co/acme/2193db3f-77c5-43b8-b030-8f92c9882bf1", ("lever", "acme", "2193db3f-77c5-43b8-b030-8f92c9882bf1", True)),
    ("https://jobs.ashbyhq.com/openai/8fb1615c-34bf-47c4-a1d1-b7b2f836bbd3/application", ("ashby", "openai", "8fb1615c-34bf-47c4-a1d1-b7b2f836bbd3", False)),
])
def test_detects_supported_jobs(url, expected):
    target = detect_ats(url)
    assert (target.ats, target.board, target.job_id, target.eu) == expected


@pytest.mark.parametrize("url", [
    None, "", "not a url", "https://www.linkedin.com/jobs/view/123",
    "https://job-boards.greenhouse.io/anthropic", "https://jobs.lever.co/spotify",
    "https://jobs.ashbyhq.com/openai", "https://acme.wd1.myworkdayjobs.com/en-US/careers/job/123",
])
def test_ignores_other_urls(url):
    assert detect_ats(url) is None


def test_form_urls():
    assert detect_ats("https://boards.greenhouse.io/figma/jobs/5").form_url == "https://job-boards.greenhouse.io/figma/jobs/5"
    lever = "https://jobs.lever.co/spotify/2193db3f-77c5-43b8-b030-8f92c9882bf1"
    assert detect_ats(lever).form_url == lever + "/apply"
    ashby = "https://jobs.ashbyhq.com/openai/8fb1615c-34bf-47c4-a1d1-b7b2f836bbd3"
    assert detect_ats(ashby).form_url == ashby + "/application"
    assert detect_ats("https://stripe.com/jobs/1?gh_jid=1").form_url is None


GREENHOUSE = {
    "questions": [
        {"required": True, "label": "First Name", "fields": [{"name": "first_name", "type": "input_text", "values": []}]},
        {"required": True, "label": "Email", "fields": [{"name": "email", "type": "input_text", "values": []}]},
        {"required": True, "label": "Phone", "fields": [{"name": "phone", "type": "input_text", "values": []}]},
        {"required": False, "label": "Resume/CV", "fields": [
            {"name": "resume", "type": "input_file", "values": []},
            {"name": "resume_text", "type": "textarea", "values": []},
        ]},
        {"required": True, "label": "Why Anthropic?", "description": "<p>A few <b>sentences</b>.</p>",
         "fields": [{"name": "question_1", "type": "textarea", "values": []}]},
        {"required": True, "label": "Will you require sponsorship?", "fields": [
            {"name": "question_2", "type": "multi_value_single_select",
             "values": [{"label": "Yes", "value": 1}, {"label": "No", "value": 0}]},
        ]},
        {"required": True, "label": "Countries", "fields": [
            {"name": "question_3[]", "type": "multi_value_multi_select",
             "values": [{"label": "UK", "value": 7}, {"label": "Other", "value": 9}]},
        ]},
    ],
    "location_questions": [
        {"required": True, "label": "Location", "fields": [{"name": "location", "type": "input_text"}]},
        {"required": True, "label": "Latitude", "fields": [{"name": "latitude", "type": "input_hidden"}]},
    ],
    "compliance": [{"type": "eeoc", "questions": [
        {"required": False, "label": "Gender", "fields": [{"name": "gender", "type": "multi_value_single_select",
         "values": [{"label": "Male", "value": 1}, {"label": "Decline To Self Identify", "value": 3}]}]},
    ]}],
    "demographic_questions": {"questions": [
        {"id": 55, "label": "Pronouns", "required": False, "type": "multi_value_multi_select",
         "answer_options": [{"id": 1, "label": "she/her"}, {"id": 2, "label": "I prefer not to answer"}]},
    ]},
    "data_compliance": [{"type": "gdpr", "requires_consent": False, "requires_processing_consent": True,
                         "requires_retention_consent": False}],
}


def test_parse_greenhouse():
    fields = {f["key"]: f for f in parse_greenhouse(GREENHOUSE)}
    assert list(fields) == [
        "first_name", "email", "phone", "resume", "question_1", "question_2", "question_3[]",
        "location", "gender", "demographic_55", "data_compliance_gdpr_processing",
    ]
    assert fields["email"]["type"] == "email" and fields["phone"]["type"] == "phone"
    assert fields["resume"]["type"] == "file" and fields["resume"]["required"] is False
    assert fields["question_1"]["type"] == "textarea"
    assert fields["question_1"]["description"] == "A few sentences."
    assert fields["question_2"]["options"] == [{"label": "Yes", "value": "1"}, {"label": "No", "value": "0"}]
    assert fields["question_3[]"]["type"] == "multiselect"
    assert fields["location"]["type"] == "location" and fields["location"]["required"]
    assert fields["gender"]["group"] == "voluntary"
    assert fields["demographic_55"]["options"][1] == {"label": "I prefer not to answer", "value": "2"}
    assert fields["data_compliance_gdpr_processing"]["type"] == "boolean"
    assert fields["data_compliance_gdpr_processing"]["required"]


ASHBY = {"data": {"jobPosting": {
    "id": "x",
    "applicationForm": {"sections": [{"fieldEntries": [
        {"field": {"path": "_systemfield_name", "title": "Legal Name", "type": "String"}, "isRequired": True,
         "descriptionHtml": "<p>As on your ID.</p>"},
        {"field": {"path": "_systemfield_resume", "title": "Resume", "type": "File"}, "isRequired": True},
        {"field": {"path": "abc", "title": "Authorized to work?", "type": "Boolean"}, "isRequired": True},
        {"field": {"path": "old", "title": "Removed", "type": "String", "isDeactivated": True}, "isRequired": True},
        {"field": {"path": "agree", "title": "Arbitration", "type": "MultiValueSelect",
                   "selectableValues": [{"label": "I acknowledge", "value": "I acknowledge"}]}, "isRequired": True},
        {"id": "no-field-entry"},
    ]}]},
    "surveyForms": [{"id": "s1", "sections": [{"fieldEntries": [
        {"field": {"path": "gender", "title": "Gender", "type": "ValueSelect",
                   "selectableValues": [{"label": "Decline to self-identify", "value": "decline"}]}, "isRequired": False},
    ]}]}],
}}}


def test_parse_ashby():
    fields = {f["key"]: f for f in parse_ashby(ASHBY)}
    assert list(fields) == ["_systemfield_name", "_systemfield_resume", "abc", "agree", "survey:s1:gender"]
    assert fields["_systemfield_name"]["description"] == "As on your ID."
    assert fields["abc"]["type"] == "boolean"
    assert fields["agree"]["type"] == "multiselect" and fields["agree"]["required"]
    assert fields["survey:s1:gender"]["group"] == "voluntary"


def test_parse_ashby_closed_posting():
    with pytest.raises(FormUnavailable) as e:
        parse_ashby({"data": {"jobPosting": None}})
    assert e.value.closed


def _template(template_id, kind, fields):
    value = html.escape(json.dumps({"id": template_id, "fields": fields}), quote=True)
    return f'<input type="hidden" value="{value}" name="{kind}[{template_id}][baseTemplate]">'


LEVER_PAGE = f"""<html><body><form id="application-form" enctype="multipart/form-data" method="POST"><ul>
<li class="application-question" data-qa="opportunity-location-question"><div class="application-label">Office?</div>
<div class="application-field"><select name="opportunityLocationId"><option value="">Select...</option>
<option value="l1">London</option><option value="l2">Stockholm</option></select></div></li>
<li class="application-question resume"><label><div class="application-label">Resume/CV <span class="required">✱</span></div>
<div class="application-field"><a><input class="application-file-input" name="resume" type="file"></a></div></label></li>
<li class="application-question"><label><div class="application-label">Full name<span class="required">✱</span></div>
<div class="application-field"><input type="text" name="name" required></div></label></li>
<li class="application-question"><div class="application-label">Pronouns</div><div class="application-field"><ul>
<li><label><input type="checkbox" name="pronouns" value="she/her"><span>She/her</span></label></li>
<li><label><input type="checkbox" name="pronouns" value="they/them"><span>They/them</span></label></li></ul></div></li>
<li class="application-question"><label><div class="application-label">Email <span class="required">✱</span></div>
<div class="application-field"><input type="email" name="email" required></div></label></li>
<li class="application-question"><label><div class="application-label">Current location <span class="required">✱</span></div>
<div class="application-field"><input type="text" name="location" required><input type="hidden" name="selectedLocation"></div></label></li>
<li class="application-question"><label><div class="application-label">LinkedIn URL</div>
<div class="application-field"><input type="text" name="urls[LinkedIn]"></div></label></li>
<li class="application-question"><label><div class="application-label">Additional information</div>
<div class="application-field"><textarea name="comments"></textarea></div></label></li>
</ul>
<div>{_template("c1", "cards", [
    {"type": "multiple-choice", "text": "Previously employed by Spotify?", "required": True,
     "options": [{"text": "No"}, {"text": "Yes - Intern"}]},
    {"type": "textarea", "text": "Tell us more", "required": False},
])}<ul><li class="application-question custom-question"><div class="application-label">Previously employed by Spotify?</div>
<div class="application-field"><input type="radio" name="cards[c1][field0]" value="No"></div></li></ul></div>
<div>{_template("s1", "surveysResponses", [
    {"type": "multiple-choice", "text": "Gender", "required": True, "options": [{"text": "Prefer not to disclose"}]},
])}</div>
<ul><li class="application-question"><div class="application-field full-width"><ul><li><label>
<span class="">Spotify may contact me about future job opportunities.</span>
<input type="hidden" name="consent[marketing]" value="0"><input type="checkbox" name="consent[marketing]" value="1"></label></li></ul></div></li></ul>
</form></body></html>"""


def test_parse_lever():
    fields = {f["key"]: f for f in parse_lever(LEVER_PAGE)}
    assert list(fields) == [
        "opportunityLocationId", "resume", "name", "pronouns", "email", "location", "urls[LinkedIn]", "comments",
        "consent[marketing]", "cards[c1][field0]", "cards[c1][field1]", "surveysResponses[s1][responses][field0]",
    ]
    assert fields["opportunityLocationId"]["options"] == [{"label": "London", "value": "l1"}, {"label": "Stockholm", "value": "l2"}]
    assert fields["resume"]["type"] == "file" and fields["resume"]["required"]
    assert fields["name"]["required"] and fields["name"]["label"] == "Full name"
    assert fields["pronouns"]["type"] == "multiselect" and len(fields["pronouns"]["options"]) == 2
    assert fields["location"]["type"] == "location"
    assert fields["urls[LinkedIn]"]["type"] == "url" and not fields["urls[LinkedIn]"]["required"]
    assert fields["comments"]["type"] == "textarea"
    assert fields["consent[marketing]"]["type"] == "boolean"
    assert "future job opportunities" in fields["consent[marketing]"]["label"]
    card = fields["cards[c1][field0]"]
    assert card["type"] == "select" and card["required"] and card["options"][1]["value"] == "Yes - Intern"
    survey = fields["surveysResponses[s1][responses][field0]"]
    assert survey["group"] == "voluntary" and survey["required"] is False


def test_parse_lever_without_form():
    with pytest.raises(FormUnavailable):
        parse_lever("<html>Page not found</html>")
