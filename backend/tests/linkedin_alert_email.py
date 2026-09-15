"""A made-up LinkedIn job alert email with the structure of a real one
(template email_job_alert_digest_01, September 2026)."""

from html import escape

TRACKING = "&amp;refId=abc&amp;lipi=urn%3Ali&amp;midToken=AQG123&amp;midSig=xyz&amp;otpToken=MDcxNjhiNjM%3D"

JOBS = [
    # (job id, title, "company · location", extra lines)
    ("4100000001", "AI Automation Specialist", "Acme Talent · United States (Remote)", []),
    ("4100000002", "Automation Engineer", "Sunny Staffing · Coral Gables, FL (On-site)", ["$74K-$76K / year", "Easy Apply"]),
    ("4100000003", "Workflow Engineer", "Northwind · Toronto, ON (Hybrid)", ["CA$90K / year", "Actively recruiting"]),
    ("4100000004", "AI Engineer", "Globex · London, England, United Kingdom", ["3 school alumni"]),
]


def _link(job_id: str, element: str, position: int) -> str:
    trk = f"eml-email_job_alert_digest_01-primary_job_list-0-{element}_{position}_jobid_{job_id}_ssid_1_fmid_x"
    return f'https://www.linkedin.com/comm/jobs/view/{job_id}/?trackingId=t1{TRACKING}&amp;trk={trk}'


def _card(position: int, job_id: str, title: str, company_line: str, extras: list[str]) -> str:
    extra_rows = ""
    for line in extras:
        css = "text-system-gray-70" if "/" in line else "job-card-flavor__detail"
        extra_rows += f'<tr><td class="pb-0"><p class="{css}">{escape(line)}</p></td></tr>'
    return f"""
<tr><td class="pt-3" data-test-id="job-card"><table role="presentation"><tbody><tr>
  <td class="pr-1 w-6" valign="top"><a href="{_link(job_id, 'company_logo', position)}" target="_blank">
    <img src="https://media.licdn.com/logo.png" alt="{escape(company_line.split('·')[0].strip())}" width="48" height="48"></a></td>
  <td valign="top"><a href="{_link(job_id, 'job_posting', position)}" target="_blank"><table role="presentation"><tbody>
    <tr><td class="pb-0"><a href="{_link(job_id, 'jobcard_body', position)}" class="font-bold text-md">{escape(title)}</a></td></tr>
    <tr><td class="pb-0"><p class="text-system-gray-100 text-xs">{escape(company_line).replace('·', '&middot;')}</p></td></tr>
    <!--[if (gte mso 9)|(IE)]><table cellpadding="0"><![endif]-->
    {extra_rows}
  </tbody></table></a></td>
</tr></tbody></table></td></tr>"""


def alert_email_html(jobs=JOBS, search="Automation Engineer", location="United States") -> str:
    cards = "".join(_card(i, *job) for i, job in enumerate(jobs))
    return f"""<html><head><title>LinkedIn</title><style>.x{{color:red}}</style></head><body>
<table><tr><td><a href="https://www.linkedin.com/comm/feed/?trk=eml-email_job_alert_digest_01-header-0-home_glimmer{TRACKING}">Home</a></td></tr>
<tr><td><h1><a href="https://www.linkedin.com/comm/jobs/alerts?trk=x{TRACKING}" class="text-system-gray-90">
  Your job alert for <strong class="font-bold">{escape(search)}</strong></a></h1></td></tr>
<tr><td class="pt-1 job-alert-subheader"><h2 class="text-md font-normal" data-test-id="email-subhead">New jobs in {escape(location)} match your preferences.</h2></td></tr>
{cards}
<tr><td><a href="https://www.linkedin.com/comm/jobs/search-results/?keywords=x&amp;trk=eml-email_job_alert_digest_01-primary_job_list-0-see_all_jobs_button{TRACKING}">See all jobs</a></td></tr>
<tr><td><p>This email was intended for Test Person (AI Engineer)</p></td></tr>
</table></body></html>"""
