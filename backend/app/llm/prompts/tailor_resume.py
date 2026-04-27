SYSTEM_PROMPT = """You are an expert resume tailoring specialist. Your job is to customize a candidate's resume for a specific job posting.

CRITICAL RULES:
1. You must ONLY use information from the candidate's actual profile data provided
2. NEVER invent, fabricate, or exaggerate any experience, skills, metrics, or achievements
3. NEVER add tools, technologies, companies, or projects not in the candidate's profile
4. You CAN reorder bullets to prioritize relevant experience
5. You CAN reframe language to use the job posting's terminology WHERE TRUTHFUL
6. You CAN adjust the professional summary to align with the role
7. You CAN omit irrelevant experience to focus the resume
8. Preserve all quantified metrics exactly as they appear in the source data"""

TAILOR_RESUME_PROMPT = """Tailor this candidate's resume for the following job:

## Job Details
Title: {job_title}
Company: {job_company}
Key Requirements: {job_requirements}
Required Skills: {job_skills}
Keywords for ATS: {job_keywords}

## Candidate Profile
Headline: {candidate_headline}
Current Summary: {candidate_summary}

## Work History
{work_history_text}

## Skills
{skills_text}

## Instructions
1. Write a tailored professional summary (2-3 sentences) that positions the candidate for THIS specific role
2. Select and reorder the most relevant work experience bullets
3. Reframe bullet language to match the job's terminology where truthful
4. Identify which job keywords are matched and which are unmatched
5. Provide notes on strongest matches and gaps"""

TAILOR_TOOL = {
    "name": "generate_tailored_resume",
    "description": "Generate a tailored resume for a specific job posting",
    "input_schema": {
        "type": "object",
        "properties": {
            "tailored_summary": {
                "type": "string",
                "description": "2-3 sentence professional summary tailored to this role"
            },
            "selected_experience": {
                "type": "array",
                "description": "Work experience entries, reordered and with tailored bullets",
                "items": {
                    "type": "object",
                    "properties": {
                        "company": {"type": "string"},
                        "title": {"type": "string"},
                        "dates": {"type": "string"},
                        "bullets": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Reordered/reframed bullets (max 4-5 per role)"
                        }
                    },
                    "required": ["company", "title", "bullets"]
                }
            },
            "highlighted_skills": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Top skills to feature, ordered by relevance to this job"
            },
            "matched_keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Job keywords that match the candidate's real experience"
            },
            "unmatched_keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Job keywords NOT matched by the candidate's experience"
            },
            "strongest_matches": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-3 areas where the candidate is strongest for this role"
            },
            "gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Areas where the candidate is weakest for this role"
            }
        },
        "required": ["tailored_summary", "selected_experience", "highlighted_skills",
                      "matched_keywords", "unmatched_keywords", "strongest_matches", "gaps"]
    }
}

COVER_LETTER_PROMPT = """Write a concise cover letter for this job application:

## Job
Title: {job_title} at {job_company}
Key Requirements: {job_requirements}

## Candidate Summary
{candidate_summary}

## Top Matching Experience
{top_experience}

## Instructions
- Write 3-4 paragraphs max
- Reference 2-3 specific, real achievements from the candidate's experience
- Show genuine understanding of what the company/role needs
- Be specific, not generic — mention the company name and role
- Professional but not stiff — conversational confidence
- NEVER fabricate any experience or metrics
- End with a clear call to action"""

OUTREACH_PROMPT = """Draft a LinkedIn recruiter outreach message for this job:

## Job
Title: {job_title} at {job_company}

## Candidate's Strongest Matches
{strongest_matches}

## Instructions
- Keep it under 300 characters (LinkedIn connection request limit)
- Be direct and specific about why you're a fit
- Reference one concrete, relevant achievement
- Include a clear ask (coffee chat, learn more about the role)
- Professional but human tone
- NEVER fabricate anything"""

SUMMARY_REGEN_PROMPT = """Write only the professional summary (2-3 sentences) for this candidate's resume, tailored to this job:

## Job
Title: {job_title} at {job_company}
Key Requirements: {job_requirements}
Required Skills: {job_skills}

## Candidate
Headline: {candidate_headline}
Master summary: {candidate_summary}
Top experience: {top_experience}

{guidance_block}

## Instructions
- 2-3 sentences only — no preamble, no explanation, no quotes
- Position the candidate for THIS specific role using their real background
- Use the job's terminology where truthful
- NEVER fabricate experience, metrics, tools, or employers
- Return only the summary text"""


ANSWER_PROMPT = """Answer this screening question for a job application:

## Job
Title: {job_title} at {job_company}

## Question
{question}

## Candidate Profile
{candidate_summary}

## Relevant Experience
{relevant_experience}

## Instructions
- Answer directly and specifically
- Reference real experience from the candidate's profile
- Keep it concise (2-4 sentences unless the question requires more)
- NEVER fabricate any experience, metrics, or achievements"""
