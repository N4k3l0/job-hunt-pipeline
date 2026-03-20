DEEP_SCORE_SYSTEM_PROMPT = """You are an expert career advisor and job fit analyst. Your job is to provide a thorough, honest assessment of how well a candidate matches a specific job posting.

RULES:
1. Be specific — reference actual skills, experience, and requirements by name
2. Be honest — if the candidate is not a good fit, say so clearly
3. Consider both explicit requirements AND implicit ones (industry norms, seniority signals)
4. Weight must-have requirements more heavily than nice-to-haves
5. Consider transferable skills and adjacent experience, not just exact keyword matches
6. Factor in seniority alignment — overqualified is a mismatch just like underqualified"""

DEEP_SCORE_USER_PROMPT = """Analyze how well this candidate fits the following job posting.

## Job Posting
Title: {job_title}
Company: {job_company}
Location: {job_location}
Remote Type: {job_remote_type}
Seniority Level: {job_seniority}

### Full Job Description
{job_description}

### Parsed Requirements
Required Skills: {job_skills}
Key Requirements: {job_requirements}
Nice to Have: {job_nice_to_have}
Experience Range: {job_experience_range}

## Candidate Profile
Headline: {candidate_headline}
Summary: {candidate_summary}

### Work History
{work_history_text}

### Skills
{skills_text}

### Education
{education_text}

## Instructions
Evaluate the candidate's fitness for this specific role. Consider:
1. Do they have the required skills? Which ones are missing?
2. Is their work history relevant? Give specific examples.
3. Is the seniority level appropriate?
4. Are there transferable skills that compensate for gaps?
5. Would you recommend they apply?

Be specific and reference actual data from both the job and the candidate profile."""

DEEP_SCORE_TOOL = {
    "name": "submit_deep_score",
    "description": "Submit a structured deep fitness assessment for a candidate against a job posting",
    "input_schema": {
        "type": "object",
        "properties": {
            "overall_fit_score": {
                "type": "integer",
                "description": "Overall fitness score from 0-100. 80+ = strong fit, 60-79 = good fit with some gaps, 40-59 = partial fit, below 40 = poor fit"
            },
            "strengths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific matches between the candidate's experience/skills and the job requirements. Each item should reference a concrete skill or experience."
            },
            "gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Job requirements the candidate does not clearly meet. Be specific about what is missing."
            },
            "experience_relevance": {
                "type": "object",
                "description": "Assessment of how relevant the candidate's work history is",
                "properties": {
                    "score": {
                        "type": "integer",
                        "description": "Relevance score 0-100"
                    },
                    "relevant_roles": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string", "description": "The role title and company"},
                                "relevance": {"type": "string", "description": "Why this role is relevant to the target job"}
                            },
                            "required": ["role", "relevance"]
                        },
                        "description": "Which past roles are most relevant and why"
                    },
                    "summary": {
                        "type": "string",
                        "description": "1-2 sentence summary of experience relevance"
                    }
                },
                "required": ["score", "relevant_roles", "summary"]
            },
            "skill_match_details": {
                "type": "object",
                "description": "Detailed skill matching analysis",
                "properties": {
                    "matched_skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Required skills the candidate has"
                    },
                    "missing_skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Required skills the candidate lacks"
                    },
                    "transferable_skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Skills the candidate has that are adjacent or transferable to requirements"
                    },
                    "bonus_skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Nice-to-have skills the candidate has"
                    }
                },
                "required": ["matched_skills", "missing_skills", "transferable_skills", "bonus_skills"]
            },
            "recommendation": {
                "type": "string",
                "enum": ["strong_apply", "apply", "maybe", "skip"],
                "description": "Overall recommendation: strong_apply (80+), apply (60-79), maybe (40-59), skip (below 40)"
            },
            "summary": {
                "type": "string",
                "description": "2-3 sentence plain language assessment of the candidate's fit for this role. Be direct and specific."
            }
        },
        "required": [
            "overall_fit_score",
            "strengths",
            "gaps",
            "experience_relevance",
            "skill_match_details",
            "recommendation",
            "summary"
        ]
    }
}
