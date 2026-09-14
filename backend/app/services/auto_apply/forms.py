"""Read a job's application form into one shape for every hiring system.

Each field is a dict:

    key          what the form calls the field; unique within the form
    label        the question as the applicant sees it
    type         text | textarea | email | phone | url | number | date |
                 file | select | multiselect | boolean | location
    required     whether the form refuses to submit without it
    options      [{"label", "value"}] for select and multiselect
    description  extra text shown with the question (plain text)
    group        "application", or "voluntary" for demographic surveys

Greenhouse and Ashby publish the form as JSON. Lever's form is read from
its apply page, which embeds each custom question's definition as JSON.
"""

from __future__ import annotations

import html
import json
import re

import httpx

from app.services.auto_apply.ats import AtsTarget

USER_AGENT = "Mozilla/5.0 (compatible; JobHuntPipeline/1.0; +application-prep)"
TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)


class FormUnavailable(Exception):
    """The form can't be read. `closed` means the posting is gone."""

    def __init__(self, message: str, closed: bool = False):
        super().__init__(message)
        self.closed = closed


def _text(markup: str | None) -> str:
    if not markup:
        return ""
    text = re.sub(r"<(br|/p|/li|/div)[^>]*>", "\n", markup, flags=re.I)
    text = re.sub(r"</?(b|i|u|em|strong|a|span|code)\b[^>]*>", "", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _field(key, label, type_, required=False, options=None, description=None, group="application") -> dict:
    return {
        "key": key,
        "label": " ".join((label or "").split()) or key,
        "type": type_,
        "required": bool(required),
        "options": options,
        "description": description or None,
        "group": group,
    }


# ─── Greenhouse ─────────────────────────────────────────────────────────────

_GREENHOUSE_TYPES = {
    "input_text": "text",
    "textarea": "textarea",
    "input_file": "file",
    "multi_value_single_select": "select",
    "multi_value_multi_select": "multiselect",
}


def _greenhouse_options(values) -> list[dict] | None:
    if not values:
        return None
    return [{"label": str(v.get("label")), "value": str(v.get("value"))} for v in values]


def parse_greenhouse(data: dict) -> list[dict]:
    fields: list[dict] = []
    for q in data.get("questions") or []:
        inputs = [f for f in q.get("fields") or [] if f.get("type") != "input_hidden"]
        if not inputs:
            continue
        label, required = q.get("label"), q.get("required")
        description = _text(q.get("description"))
        file_input = next((f for f in inputs if f.get("type") == "input_file"), None)
        if file_input:
            fields.append(_field(file_input["name"], label, "file", required, description=description))
            continue
        f = inputs[0]
        type_ = _GREENHOUSE_TYPES.get(f.get("type"), "text")
        if f["name"] == "email":
            type_ = "email"
        elif f["name"] == "phone":
            type_ = "phone"
        fields.append(_field(
            f["name"], label, type_, required, _greenhouse_options(f.get("values")), description,
        ))

    for q in data.get("location_questions") or []:
        if any(f.get("name") == "location" for f in q.get("fields") or []):
            fields.append(_field("location", q.get("label") or "Location", "location", q.get("required")))

    for block in data.get("compliance") or []:
        for q in block.get("questions") or []:
            for f in q.get("fields") or []:
                fields.append(_field(
                    f["name"], q.get("label"), _GREENHOUSE_TYPES.get(f.get("type"), "select"),
                    q.get("required"), _greenhouse_options(f.get("values")), group="voluntary",
                ))

    demographic = data.get("demographic_questions") or {}
    for q in demographic.get("questions") or []:
        options = [{"label": str(o.get("label")), "value": str(o.get("id"))} for o in q.get("answer_options") or []]
        fields.append(_field(
            f"demographic_{q.get('id')}", q.get("label"),
            "multiselect" if q.get("type") == "multi_value_multi_select" else "select",
            q.get("required"), options or None, group="voluntary",
        ))

    for block in data.get("data_compliance") or []:
        kind = (block.get("type") or "data").upper()
        if block.get("requires_processing_consent") or block.get("requires_consent"):
            fields.append(_field(
                f"data_compliance_{block.get('type')}_processing", f"{kind}: I consent to the processing of my personal data",
                "boolean", True,
            ))
        if block.get("requires_retention_consent"):
            fields.append(_field(
                f"data_compliance_{block.get('type')}_retention", f"{kind}: I consent to my personal data being retained",
                "boolean", True,
            ))
    return fields


# ─── Ashby ──────────────────────────────────────────────────────────────────

_ASHBY_TYPES = {
    "String": "text",
    "Email": "email",
    "Phone": "phone",
    "File": "file",
    "LongText": "textarea",
    "Boolean": "boolean",
    "ValueSelect": "select",
    "MultiValueSelect": "multiselect",
    "Date": "date",
    "Number": "number",
    "Location": "location",
    "SocialLink": "url",
}

_ASHBY_QUERY = """
query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {
  jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) {
    id
    applicationForm { sections { fieldEntries { ... on FormFieldEntry { field isRequired descriptionHtml } } } }
    surveyForms { id sections { fieldEntries { ... on FormFieldEntry { field isRequired descriptionHtml } } } }
  }
}
"""


def _ashby_entries(form: dict | None, group: str, key_prefix: str = "") -> list[dict]:
    fields: list[dict] = []
    for section in (form or {}).get("sections") or []:
        for entry in section.get("fieldEntries") or []:
            f = entry.get("field") or {}
            if not f.get("path") or f.get("isDeactivated"):
                continue
            options = [
                {"label": str(v.get("label")), "value": str(v.get("value"))}
                for v in f.get("selectableValues") or []
            ] or None
            fields.append(_field(
                key_prefix + f["path"], f.get("title"), _ASHBY_TYPES.get(f.get("type"), "text"),
                entry.get("isRequired"), options, _text(entry.get("descriptionHtml")), group,
            ))
    return fields


def parse_ashby(data: dict) -> list[dict]:
    posting = (data.get("data") or {}).get("jobPosting")
    if not posting:
        raise FormUnavailable("This posting is no longer listed", closed=True)
    fields = _ashby_entries(posting.get("applicationForm"), "application")
    for survey in posting.get("surveyForms") or []:
        fields += _ashby_entries(survey, "voluntary", key_prefix=f"survey:{survey.get('id')}:")
    return fields


# ─── Lever ──────────────────────────────────────────────────────────────────

_LEVER_CARD_TYPES = {
    "multiple-choice": "select",
    "dropdown": "select",
    "multiple-select": "multiselect",
    "text": "text",
    "textarea": "textarea",
    "file-upload": "file",
    "date": "date",
}

_TEMPLATE_INPUT = re.compile(
    r'<input\b(?=[^>]*\bname="(cards|surveysResponses)\[([^\]]+)\]\[baseTemplate\]")[^>]*>'
)


def _lever_templates(page: str) -> list[dict]:
    fields: list[dict] = []
    for match in _TEMPLATE_INPUT.finditer(page):
        kind, template_id = match.group(1), match.group(2)
        value = re.search(r'\bvalue="([^"]*)"', match.group(0))
        try:
            template = json.loads(html.unescape(value.group(1))) if value else {}
        except ValueError:
            continue
        for i, f in enumerate(template.get("fields") or []):
            if kind == "cards":
                key, group = f"cards[{template_id}][field{i}]", "application"
            else:
                key, group = f"surveysResponses[{template_id}][responses][field{i}]", "voluntary"
            options = [{"label": o["text"], "value": o["text"]} for o in f.get("options") or [] if o.get("text")]
            fields.append(_field(
                key, f.get("text"), _LEVER_CARD_TYPES.get(f.get("type"), "text"),
                f.get("required") and group == "application", options or None,
                _text(f.get("description")), group,
            ))
    return fields


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return html.unescape(m.group(1)) if m else None


def _lever_standard(form_html: str) -> list[dict]:
    fields: list[dict] = []
    blocks = re.split(r'<li\b[^>]*class="application-question', form_html)[1:]
    for block in blocks:
        tags = re.findall(r"<(input|select|textarea)\b[^>]*>", block)
        controls = [
            m for m in re.finditer(r"<(input|select|textarea)\b[^>]*>", block)
            if _attr(m.group(0), "type") != "hidden" and _attr(m.group(0), "name")
        ]
        if not tags or not controls:
            continue
        tag = controls[0].group(0)
        name = _attr(tag, "name")
        if name.startswith(("cards[", "surveysResponses[")):
            continue
        label_match = re.search(r'class="application-label[^"]*">([\s\S]*?)</div>', block)
        label_html = label_match.group(1) if label_match else ""
        label = _text(label_html).replace("✱", "").strip()
        required = 'class="required"' in label_html or "required" in (tag.split(">")[0].split())
        element = controls[0].group(1)
        input_type = _attr(tag, "type") or ""

        if name == "consent[marketing]":
            label = _text(re.search(r"<span[^>]*>([\s\S]*?)</span>", block).group(1)) if "<span" in block else "Marketing consent"
            fields.append(_field(name, label, "boolean", False))
            continue
        if input_type == "file":
            fields.append(_field(name, label or "Resume/CV", "file", required))
        elif element == "select":
            select_html = block[controls[0].start():]
            options = [
                {"label": _text(text), "value": html.unescape(value)}
                for value, text in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([\s\S]*?)</option>', select_html)
                if value
            ]
            fields.append(_field(name, label, "select", required, options or None))
        elif input_type == "checkbox":
            options = [
                {"label": _text(text), "value": html.unescape(value)}
                for value, text in re.findall(
                    r'<input[^>]*type="checkbox"[^>]*value="([^"]*)"[^>]*>\s*(?:<span[^>]*>([\s\S]*?)</span>)?', block
                )
            ]
            fields.append(_field(name, label, "multiselect", required, options or None))
        elif element == "textarea":
            fields.append(_field(name, label, "textarea", required))
        else:
            type_ = {"email": "email", "phone": "phone", "location": "location"}.get(name, "text")
            if name.startswith("urls["):
                type_ = "url"
            fields.append(_field(name, label, type_, required))
    return fields


def parse_lever(page: str) -> list[dict]:
    start = page.find('id="application-form"')
    if start == -1:
        raise FormUnavailable("The application form wasn't found on the posting page")
    end = page.find("</form>", start)
    form_html = page[start:end if end != -1 else len(page)]
    return _lever_standard(form_html) + _lever_templates(form_html)


# ─── Fetching ───────────────────────────────────────────────────────────────


async def fetch_form(client: httpx.AsyncClient, target: AtsTarget) -> list[dict]:
    """Read the target's application form. Raises FormUnavailable."""
    try:
        if target.ats == "greenhouse":
            host = "boards-api.eu.greenhouse.io" if target.eu else "boards-api.greenhouse.io"
            r = await client.get(
                f"https://{host}/v1/boards/{target.board}/jobs/{target.job_id}", params={"questions": "true"}
            )
            if r.status_code == 404:
                raise FormUnavailable("This posting is no longer listed", closed=True)
            r.raise_for_status()
            return parse_greenhouse(r.json())

        if target.ats == "ashby":
            r = await client.post(
                "https://jobs.ashbyhq.com/api/non-user-graphql",
                params={"op": "ApiJobPosting"},
                json={
                    "operationName": "ApiJobPosting",
                    "variables": {"organizationHostedJobsPageName": target.board, "jobPostingId": target.job_id},
                    "query": _ASHBY_QUERY,
                },
            )
            r.raise_for_status()
            return parse_ashby(r.json())

        if target.ats == "lever":
            r = await client.get(target.form_url)
            if r.status_code == 404:
                raise FormUnavailable("This posting is no longer listed", closed=True)
            r.raise_for_status()
            return parse_lever(r.text)
    except httpx.HTTPStatusError as e:
        raise FormUnavailable(f"The hiring system answered {e.response.status_code}") from e
    except httpx.HTTPError as e:
        raise FormUnavailable(f"Couldn't reach the hiring system ({type(e).__name__})") from e
    except ValueError as e:
        raise FormUnavailable("The hiring system sent a form this app couldn't read") from e
    raise FormUnavailable(f"Unsupported hiring system: {target.ats}")


def http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
