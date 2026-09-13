SYSTEM_PROMPT = """You read job postings and record the facts a job-matching system needs. Postings can be for any profession: nursing, accounting, software, sales, teaching, trades, design, and so on.

Record only what the posting states or clearly implies. Leave a field out (or a list empty) when it doesn't say.

- required_skills: concrete skills, tools, qualifications, certifications or licenses the posting asks for. Short names ("Python", "IFRS", "Registered Nurse license", "Figma"), not sentences.
- nice_to_have_skills: the same, but listed as preferred or a plus.
- requirements: the main responsibilities and requirements as short phrases, most important first.
- keywords: industry and domain terms that describe the role or company (e.g. "fintech", "B2B SaaS", "pediatrics").
- seniority: the level the role is pitched at.
- salary_min / salary_max: the amounts exactly as the posting states them, in its currency, with salary_period saying what they're per (hour, day, week, month, year). Leave salary out for per-task or per-article pay.
- eligible_countries: ISO 3166-1 alpha-2 codes of the countries applicants must live in or be authorized to work in, only when the posting restricts this (e.g. "US only", "must be based in the UK or Ireland", "EU residents"). Leave it empty when the role is open worldwide or the posting doesn't say. An office address on its own is not a restriction.
- sponsorship_available: true if visa sponsorship is offered, false if the posting says it isn't; leave it out if not mentioned."""

USER_PROMPT_TEMPLATE = """Title: {title}
Company: {company}
Location: {location}

Posting:
{description}"""

RECORD_TOOL = {
    "name": "record_job_details",
    "description": "Record the extracted details of the job posting.",
    "input_schema": {
        "type": "object",
        "properties": {
            "required_skills": {"type": "array", "items": {"type": "string"}},
            "nice_to_have_skills": {"type": "array", "items": {"type": "string"}},
            "requirements": {"type": "array", "items": {"type": "string"}},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "seniority": {
                "type": "string",
                "enum": ["entry", "mid", "senior", "lead", "director", "vp", "c_level"],
            },
            "years_experience_min": {"type": "integer"},
            "years_experience_max": {"type": "integer"},
            "employment_type": {
                "type": "string",
                "enum": ["full_time", "part_time", "contract", "freelance", "internship"],
            },
            "remote_type": {"type": "string", "enum": ["full_remote", "hybrid", "onsite"]},
            "eligible_countries": {"type": "array", "items": {"type": "string"}},
            "sponsorship_available": {"type": "boolean"},
            "visa_notes": {"type": "string"},
            "salary_min": {"type": "number"},
            "salary_max": {"type": "number"},
            "salary_period": {"type": "string", "enum": ["hour", "day", "week", "month", "year"]},
            "salary_currency": {"type": "string"},
        },
        "required": ["required_skills", "nice_to_have_skills", "requirements", "keywords", "eligible_countries"],
    },
}
