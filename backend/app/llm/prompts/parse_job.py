SYSTEM_PROMPT = """You are an expert job posting parser. Extract structured data from the job description provided.

Rules:
- Extract ONLY what is explicitly stated in the posting
- For salary, normalize to annual amounts if possible
- For remote_type, classify as: full_remote, hybrid, onsite, or null if unclear
- For seniority, classify as: entry, mid, senior, lead, director, vp, c_level
- For application_type, classify as: url, email, easy_apply, or unknown
- Separate required skills from nice-to-have skills
- Note any visa/sponsorship information explicitly mentioned
- Extract application questions if the posting lists them"""

USER_PROMPT_TEMPLATE = """Parse this job posting into structured data:

---
{job_text}
---

Extract all relevant fields including title, company, location, requirements, skills, salary, and application details."""

EXTRACT_TOOL = {
    "name": "extract_job_data",
    "description": "Extract structured data from a job posting",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "company": {"type": "string"},
            "location": {"type": "string"},
            "country": {
                "type": "string",
                "description": "ISO country code (US, CA, GB, DE, FR, NL, etc.)"
            },
            "remote_type": {
                "type": "string",
                "enum": ["full_remote", "hybrid", "onsite"]
            },
            "salary_text": {"type": "string"},
            "salary_min": {"type": "integer", "description": "Annual salary minimum in local currency"},
            "salary_max": {"type": "integer", "description": "Annual salary maximum in local currency"},
            "salary_currency": {"type": "string", "description": "USD, EUR, GBP, CAD, etc."},
            "employment_type": {
                "type": "string",
                "enum": ["full_time", "part_time", "contract", "freelance"]
            },
            "seniority": {
                "type": "string",
                "enum": ["entry", "mid", "senior", "lead", "director", "vp", "c_level"]
            },
            "application_type": {
                "type": "string",
                "enum": ["url", "email", "easy_apply", "unknown"]
            },
            "description_summary": {
                "type": "string",
                "description": "2-3 sentence summary of the role"
            },
            "required_skills": {
                "type": "array",
                "items": {"type": "string"}
            },
            "nice_to_have_skills": {
                "type": "array",
                "items": {"type": "string"}
            },
            "requirements": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key responsibilities and requirements"
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Important keywords for ATS matching"
            },
            "years_experience_min": {"type": "integer"},
            "years_experience_max": {"type": "integer"},
            "visa_notes": {
                "type": "string",
                "description": "Any mention of visa sponsorship or work authorization"
            },
            "sponsorship_available": {
                "type": "boolean",
                "description": "true if sponsorship is explicitly offered, false if explicitly not, null if not mentioned"
            },
            "application_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Screening questions listed in the posting"
            },
            "apply_url": {"type": "string"},
            "contact_email": {"type": "string"},
            "deadline": {"type": "string", "description": "Application deadline if mentioned"}
        },
        "required": ["title", "company", "required_skills", "requirements", "keywords"]
    }
}
