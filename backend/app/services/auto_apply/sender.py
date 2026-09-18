"""Send an approved application from the server, in a real browser.

It opens the company's form, fills it in with the same filler the Chrome
extension uses (`extension/fill.js`), and presses Submit once. Nothing here
disguises the browser: if the form turns it away, or asks the applicant to
prove they're human, the run stops and says so. Never work around that.

    python -m app.services.auto_apply.sender <application-id> [--dry-run]

With --dry-run it fills the form in and reports, without sending.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.database import create_worker_session
from app.models.auto_apply import AutoApplication
from app.models.candidate import Resume
from app.models.user import User
from app.services.auto_apply.extension import fill_details, mark_sent
from app.services.auto_apply.resume_pdf import (
    render_pdf,
    resume_html,
    tailored_resume_data,
)
from app.services.storage import download_file, object_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sender")

FILLER_PATH = Path(os.environ.get("FORM_FILLER_PATH", Path(__file__).parents[4] / "extension" / "fill.js"))
SENT_URLS = ("/thanks", "/confirmation")
SUCCESS_TEXT = "thank you for applying|thanks for applying|application (has been |was )?(successfully )?(submitted|received)"
FILL_TIMEOUT_MS = 120_000
SUBMIT_WAIT_SECONDS = 90


class SendRefused(RuntimeError):
    """The application can't be sent: the caller shouldn't retry as-is."""


async def _resume_file(db, application: AutoApplication, page) -> dict | None:
    """The resume to attach: the tailored one for this job when there is
    one, else the file on the user's profile."""
    tailored = await tailored_resume_data(db, application.user_id, application.job_id)
    user = await db.get(User, application.user_id)
    first_name = ((user.name if user else "") or "").strip().split(" ")[0]
    if tailored:
        pdf = await render_pdf(page, resume_html(tailored))
        logger.info("Attaching the tailored resume (%d KB)", len(pdf) // 1024)
        return {"name": f"{first_name + ' ' if first_name else ''}Resume.pdf", "type": "application/pdf",
                "base64": base64.b64encode(pdf).decode()}

    resume = await db.get(Resume, application.resume_id) if application.resume_id else None
    if resume is None:
        return None
    content = await download_file("resumes", object_path("resumes", resume.file_url))
    extension = (resume.source_type or "pdf").lower()
    types = {"pdf": "application/pdf",
             "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    logger.info("Attaching the profile resume (%d KB)", len(content) // 1024)
    return {"name": f"{first_name + ' ' if first_name else ''}Resume.{extension}", "type": types.get(extension, "application/pdf"),
            "base64": base64.b64encode(content).decode()}


async def _fill(page, payload: dict, resume: dict | None) -> dict:
    """Run the extension's filler on the open form and return what it did."""
    # Wrapped in a function so Playwright runs the filler rather than
    # trying to read it as one.
    await page.evaluate("() => {" + FILLER_PATH.read_text() + "}")
    await page.evaluate(
        "([application, resume]) => window.postMessage({ jobHunt: 'to-page', type: 'fill', application, resume }, location.origin)",
        [payload, resume],
    )
    await page.wait_for_function("window.__jobHuntResult !== undefined", timeout=FILL_TIMEOUT_MS)
    return await page.evaluate("window.__jobHuntResult")


async def _submit_button(page):
    buttons = page.locator("button:visible, input[type=submit]:visible")
    for i in range(await buttons.count()):
        button = buttons.nth(i)
        label = ((await button.inner_text()) or (await button.get_attribute("value")) or "").strip()
        if "submit" in label.lower() or "send application" in label.lower():
            return button, label
    return None, None


async def _ask_page(page, script: str, *args) -> bool:
    """Run a check on the page, treating a page that's busy navigating as
    "not yet"."""
    try:
        return bool(await page.evaluate(script, *args))
    except Exception:  # noqa: BLE001 — the page navigated mid-check
        return False


async def _looks_sent(page) -> bool:
    if any(token in page.url for token in SENT_URLS):
        return True
    return await _ask_page(page,
        """(pattern) => {
            const form = document.querySelector('#application-form, #application_form, [data-field-path]');
            if (form) return false;
            return new RegExp(pattern, 'i').test(document.body ? document.body.innerText : '');
        }""",
        SUCCESS_TEXT,
    )


async def _human_check_showing(page) -> bool:
    return await _ask_page(page,
        """() => [...document.querySelectorAll('iframe')].some((frame) => {
            const src = frame.src || '';
            if (!/hcaptcha\\.com|recaptcha\\/api2\\/bframe|challenges\\.cloudflare\\.com/.test(src)) return false;
            const box = frame.getBoundingClientRect();
            return box.width > 100 && box.height > 100 && getComputedStyle(frame).visibility !== 'hidden';
        })""",
    )


async def send_application(application_id: uuid.UUID, *, dry_run: bool) -> dict:
    from playwright.async_api import async_playwright

    session = create_worker_session()
    async with session() as db:
        application = await db.get(AutoApplication, application_id)
        if application is None:
            raise SendRefused("No such application")
        if application.status == "submitted":
            raise SendRefused("This application was already sent")
        if application.status != "queued":
            raise SendRefused(f"The answers aren't approved yet (status: {application.status})")
        payload = await fill_details(db, application)
        if not payload.get("form_url"):
            raise SendRefused("This application has no form to fill in")

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            context = await browser.new_context(viewport={"width": 1280, "height": 1600})
            page = await context.new_page()
            try:
                resume = await _resume_file(db, application, page)
                logger.info("Opening %s", payload["form_url"])
                await page.goto(payload["form_url"], wait_until="domcontentloaded", timeout=60_000)
                filled = await _fill(page, payload, resume)
                missing = [item for item in filled["items"] if item["status"] == "todo"]
                logger.info("Filled in %d answers; %d need a person", filled["filled"], len(missing))
                for item in missing:
                    logger.info("  not filled in: %s — %s", item["label"][:70], item["note"])
                outcome = {"filled": filled["filled"], "not_filled": missing, "url": page.url,
                           "at": datetime.now(timezone.utc).isoformat()}

                if missing:
                    outcome["status"] = "incomplete"
                elif dry_run:
                    outcome["status"] = "dry_run"
                else:
                    button, label = await _submit_button(page)
                    if button is None:
                        outcome["status"] = "no_submit_button"
                    else:
                        logger.info("Pressing %r", label)
                        await button.click()
                        outcome["status"] = await _watch_after_submit(page)
                        outcome["url"] = page.url

                path = Path(os.environ.get("SENDER_SCREENSHOT_DIR", "/tmp")) / f"sender-{application_id}.png"
                await page.screenshot(path=str(path), full_page=True)
                logger.info("Screenshot: %s", path)
            finally:
                await context.close()
                await browser.close()

        application.result = outcome
        if outcome["status"] == "submitted":
            await mark_sent(db, application)
        else:
            await db.commit()
    return outcome


async def _watch_after_submit(page) -> str:
    """What the form did with it. Waits for the page to settle."""
    for _ in range(SUBMIT_WAIT_SECONDS):
        await asyncio.sleep(1)
        if await _looks_sent(page):
            return "submitted"
        if await _human_check_showing(page):
            logger.info("The form is asking the applicant to prove they're human. Stopping.")
            return "human_check"
    return "no_confirmation"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("application_id", nargs="?", default=os.environ.get("SEND_APPLICATION_ID"))
    parser.add_argument("--dry-run", action="store_true", default=os.environ.get("SEND_DRY_RUN") == "true")
    args = parser.parse_args()
    if not args.application_id:
        raise SystemExit("Pass an application id (or set SEND_APPLICATION_ID)")
    outcome = asyncio.run(send_application(uuid.UUID(args.application_id), dry_run=args.dry_run))
    logger.info("Outcome: %s", json.dumps(outcome)[:2000])


if __name__ == "__main__":
    main()
