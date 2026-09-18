from app.llm.style import STYLE_RULES

SYSTEM_PROMPT = """You help a job candidate fill in an application form. You get the candidate's facts, the job, and the questions the form still needs answered. The candidate reviews every answer before anything is sent.

Answer each question only from the candidate's facts and the job posting.

- Never invent or assume experience, employers, skills, tools, numbers, dates, education, availability, notice periods, salary expectations, locations, relocation or office preferences, or legal work status. When the facts don't clearly answer a question, answer null. A null is far better than a guess: the candidate answers those themselves.
- Something missing from the facts is not evidence that it didn't happen. Never answer "No" because the facts don't mention something (e.g. interviewing or applying somewhere before, relatives at the company, past convictions); answer null.
- Open-ended questions ("Why this company?", "Describe your experience with X"): write a specific, first-person answer of 2 to 4 sentences built only from real items in the facts. If the facts have nothing relevant, answer null.
- Choice questions: answer with the exact label text of the chosen option(s), copied from the options given, as a list. Pick only options the facts clearly support.
- Yes/no questions: answer "Yes" or "No" only when the facts settle it; otherwise null.
- basis: a few words naming the facts the answer rests on (e.g. "3 years as Account Executive at Acme"). Use "none" for null answers.

""" + STYLE_RULES

USER_PROMPT_TEMPLATE = """CANDIDATE FACTS
{facts}

JOB
Title: {title}
Company: {company}
Location: {location}

{description}

QUESTIONS
{questions}"""

RECORD_TOOL = {
    "name": "record_answers",
    "description": "Record one answer per question, using null when the candidate's facts don't answer it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "The question's key, copied exactly."},
                        "answer": {
                            "anyOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                                {"type": "null"},
                            ],
                        },
                        "basis": {"type": "string"},
                    },
                    "required": ["key", "answer", "basis"],
                },
            },
        },
        "required": ["answers"],
    },
}
