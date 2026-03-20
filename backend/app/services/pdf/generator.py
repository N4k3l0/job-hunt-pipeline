import logging
import tempfile

from jinja2 import Template

from app.services.storage import upload_file

logger = logging.getLogger(__name__)

RESUME_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {
    size: letter;
    margin: 0.6in 0.7in;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.45;
    color: #1a1a1a;
  }
  h1 {
    font-size: 18pt;
    font-weight: 700;
    margin-bottom: 2pt;
    letter-spacing: -0.3pt;
  }
  .summary {
    font-size: 10pt;
    color: #333;
    margin-bottom: 14pt;
    line-height: 1.5;
  }
  .section-title {
    font-size: 9pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1pt;
    color: #555;
    border-bottom: 1px solid #ddd;
    padding-bottom: 3pt;
    margin-top: 14pt;
    margin-bottom: 8pt;
  }
  .job-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 3pt;
  }
  .job-title {
    font-size: 11pt;
    font-weight: 600;
  }
  .job-company {
    font-size: 10pt;
    color: #444;
  }
  .job-dates {
    font-size: 9pt;
    color: #777;
    white-space: nowrap;
  }
  ul {
    padding-left: 14pt;
    margin-top: 3pt;
    margin-bottom: 10pt;
  }
  li {
    margin-bottom: 2pt;
    font-size: 10pt;
  }
  .skills-list {
    font-size: 10pt;
    color: #333;
    line-height: 1.6;
  }
</style>
</head>
<body>

<h1>{{ name or "Candidate Name" }}</h1>
<div class="summary">{{ summary }}</div>

<div class="section-title">Experience</div>
{% for exp in experience %}
<div class="job-header">
  <div>
    <span class="job-title">{{ exp.title }}</span>
    <span class="job-company"> · {{ exp.company }}</span>
  </div>
  {% if exp.dates %}
  <span class="job-dates">{{ exp.dates }}</span>
  {% endif %}
</div>
<ul>
{% for bullet in exp.bullets %}
  <li>{{ bullet }}</li>
{% endfor %}
</ul>
{% endfor %}

{% if skills %}
<div class="section-title">Skills</div>
<div class="skills-list">{{ skills | join(" · ") }}</div>
{% endif %}

{% if education %}
<div class="section-title">Education</div>
{% for edu in education %}
<div><strong>{{ edu.degree or "" }} {{ edu.field or "" }}</strong> — {{ edu.institution }}{% if edu.date %}, {{ edu.date }}{% endif %}</div>
{% endfor %}
{% endif %}

</body>
</html>"""


async def generate_resume_pdf(
    tailored_data: dict,
    user_id: str,
    application_id: str,
    candidate_name: str | None = None,
    education: list[dict] | None = None,
) -> str:
    """Generate a PDF resume from tailored data and upload to storage.

    Args:
        tailored_data: Output from the tailoring LLM (selected_experience, tailored_summary, etc.)
        user_id: User ID for storage path
        application_id: Application ID for filename
        candidate_name: Candidate's name for the header
        education: Education entries

    Returns:
        URL of the uploaded PDF
    """
    template = Template(RESUME_HTML_TEMPLATE)

    html = template.render(
        name=candidate_name,
        summary=tailored_data.get("tailored_summary", ""),
        experience=tailored_data.get("selected_experience", []),
        skills=tailored_data.get("highlighted_skills", []),
        education=education or [],
    )

    # Generate PDF with WeasyPrint
    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=html).write_pdf()
    except ImportError:
        logger.warning("WeasyPrint not installed, generating HTML only")
        pdf_bytes = html.encode("utf-8")

    # Upload to storage
    filename = f"tailored_{application_id}.pdf"
    path = f"{user_id}/tailored/{filename}"

    url = await upload_file(
        bucket="resumes",
        path=path,
        content=pdf_bytes,
        content_type="application/pdf",
    )

    logger.info("Generated PDF for application %s: %s", application_id, url)
    return url
