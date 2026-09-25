"""The schema.org JobPosting many job pages embed for search engines.

When a page has one, it's the most reliable record of the job: company,
location and posting date as the employer entered them, rather than text
scraped from the page's layout.
"""

from __future__ import annotations

import json
import re

_LD_JSON = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)


def _items(data) -> list:
    if isinstance(data, list):
        return [x for item in data for x in _items(item)]
    if isinstance(data, dict):
        return [data, *_items(data.get("@graph") or [])]
    return []


def _place(location) -> str | None:
    places = location if isinstance(location, list) else [location]
    names = []
    for place in places:
        address = (place or {}).get("address") if isinstance(place, dict) else None
        if isinstance(address, dict):
            country = address.get("addressCountry")
            if isinstance(country, dict):
                country = country.get("name")
            parts = [address.get("addressLocality"), address.get("addressRegion"), country]
            text = ", ".join(str(p) for p in parts if p)
            if text and text not in names:
                names.append(text)
    return "; ".join(names) or None


def job_posting(html: str) -> dict | None:
    """Title, company, location and date posted from the page's JobPosting,
    or None when it doesn't have one."""
    for raw in _LD_JSON.findall(html or ""):
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for item in _items(data):
            if item.get("@type") != "JobPosting":
                continue
            org = item.get("hiringOrganization")
            company = org.get("name") if isinstance(org, dict) else org if isinstance(org, str) else None
            remote = str(item.get("jobLocationType") or "").upper() == "TELECOMMUTE"
            return {
                "title": (item.get("title") or "").strip() or None,
                "company": (company or "").strip() or None,
                "location": "Remote" if remote and not item.get("jobLocation") else _place(item.get("jobLocation")),
                "date_posted": item.get("datePosted"),
            }
    return None
