SYSTEM_PROMPT = """You are an expert resume parser. Extract structured data from the resume text provided.

Rules:
- Extract ONLY what is explicitly stated in the resume
- Do NOT invent, infer, or fabricate any information
- If a field is not present in the resume, leave it as None/empty
- For dates, use ISO format (YYYY-MM-DD). If only year is given, use YYYY-01-01
- For skills, categorize as: technical, soft, tool, domain
- For bullets, preserve the original text exactly as written
- Extract quantified achievements with their exact numbers"""

USER_PROMPT_TEMPLATE = """Parse this resume into structured data:

---
{resume_text}
---

Extract the following:
1. headline: A brief professional headline
2. summary: The professional summary/objective if present
3. work_history: Array of positions with company, title, start_date, end_date (None if current), description, bullets (array of achievement strings), skills used, domain_tags
4. skills: Array of skills with skill_name, category (technical/soft/tool/domain), proficiency (if mentioned)
5. education: Array with institution, degree, field, graduation_date
6. certifications: Array of certification names
7. links: Object with linkedin, github, portfolio, website URLs if present
8. target_roles: 2-3 target job titles this candidate is qualified for and likely searching for, based on their most recent role(s) and skills. Use canonical industry-standard titles (e.g. "Product Manager", "AI Engineer", "Data Scientist", "Senior Backend Engineer"). These will be used to filter the job inbox, so be precise — generic terms like "Engineer" alone are too broad."""

EXTRACT_TOOL = {
    "name": "extract_resume_data",
    "description": "Extract structured data from a resume",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "Brief professional headline (e.g. 'Senior Product Manager with 8 years in B2B SaaS')"
            },
            "summary": {
                "type": "string",
                "description": "Professional summary/objective if present"
            },
            "work_history": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "company": {"type": "string"},
                        "title": {"type": "string"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string", "description": "None if current position"},
                        "description": {"type": "string"},
                        "bullets": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "skills": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "domain_tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "e.g. product-management, ai-automation, saas, fintech"
                        }
                    },
                    "required": ["company", "title", "bullets"]
                }
            },
            "skills": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "skill_name": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": ["technical", "soft", "tool", "domain"]
                        },
                        "proficiency": {
                            "type": "string",
                            "enum": ["beginner", "intermediate", "advanced", "expert"]
                        }
                    },
                    "required": ["skill_name", "category"]
                }
            },
            "education": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "institution": {"type": "string"},
                        "degree": {"type": "string"},
                        "field": {"type": "string"},
                        "graduation_date": {"type": "string"}
                    },
                    "required": ["institution"]
                }
            },
            "links": {
                "type": "object",
                "properties": {
                    "linkedin": {"type": "string"},
                    "github": {"type": "string"},
                    "portfolio": {"type": "string"},
                    "website": {"type": "string"}
                }
            },
            "target_roles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-3 canonical job titles the candidate is qualified for, derived from recent role(s) + skills. Used to filter the job inbox."
            }
        },
        "required": ["headline", "work_history", "skills", "education"]
    }
}
