import logging

import PyPDF2
import io

from app.llm.client import llm_client
from app.llm.prompts.parse_resume import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, EXTRACT_TOOL

logger = logging.getLogger(__name__)


def extract_text_from_pdf(content: bytes) -> str:
    """Extract text from a PDF file."""
    reader = PyPDF2.PdfReader(io.BytesIO(content))
    text_parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            text_parts.append(text)
    return "\n\n".join(text_parts)


def extract_text_from_docx(content: bytes) -> str:
    """Extract text from a DOCX file."""
    import docx
    doc = docx.Document(io.BytesIO(content))
    return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])


async def parse_resume_content(content: bytes, file_type: str) -> dict:
    """Parse a resume file into structured data.

    Args:
        content: Raw file bytes
        file_type: 'pdf' or 'docx'

    Returns:
        Structured resume data dict
    """
    # Extract text
    if file_type == "pdf":
        text = extract_text_from_pdf(content)
    elif file_type == "docx":
        text = extract_text_from_docx(content)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")

    if not text.strip():
        raise ValueError("Could not extract text from resume file")

    logger.info("Extracted %d characters from %s resume", len(text), file_type)

    # Send to Claude for structured extraction
    prompt = USER_PROMPT_TEMPLATE.format(resume_text=text)
    result = await llm_client.generate_structured(
        task_type="parsing",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=prompt,
        tools=[EXTRACT_TOOL],
    )

    logger.info(
        "Parsed resume: %d work entries, %d skills",
        len(result.get("work_history", [])),
        len(result.get("skills", [])),
    )

    return result


def build_bullets_from_parsed(parsed_data: dict) -> list[dict]:
    """Extract individual bullets from parsed resume for the bullet bank."""
    bullets = []
    for entry in parsed_data.get("work_history", []):
        domain_tags = entry.get("domain_tags", [])
        skills = entry.get("skills", [])
        for bullet_text in entry.get("bullets", []):
            bullets.append({
                "text": bullet_text,
                "domain_tags": domain_tags,
                "role_tags": [],
                "keywords": skills,
            })
    return bullets
