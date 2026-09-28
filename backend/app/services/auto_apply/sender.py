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
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.core.database import create_worker_session
from app.core.logging import setup_logging
from app.models.auto_apply import AutoApplication
from app.services.auto_apply.extension import fill_details, mark_sent

logger = logging.getLogger("sender")

FILLER_PATH = Path(os.environ.get("FORM_FILLER_PATH", Path(__file__).parents[4] / "extension" / "fill.js"))
SENT_URLS = ("/thanks", "/confirmation")
SUCCESS_TEXT = "thank you for applying|thanks for applying|application (has been |was )?(successfully )?(submitted|received)"
FILL_TIMEOUT_MS = 120_000
PRESS_TIMEOUT_MS = 15_000
SUBMIT_WAIT_SECONDS = 90
SUBMIT_LABEL = re.compile(r"submit|send application", re.IGNORECASE)
# The filler shows the extension's panel ("Filled in 20 answers") in the
# page's corner, above everything. Here nobody reads it, and it sat on top
# of Greenhouse's Submit button, so the press never landed.
HIDE_PANEL = """() => {
    const style = document.createElement('style');
    style.textContent = 'job-hunt-panel { display: none !important; }';
    document.documentElement.appendChild(style);
}"""


class SendRefused(RuntimeError):
    """The application can't be sent: the caller shouldn't retry as-is."""


async def _attachment(file: dict | None) -> dict | None:
    """Download what the app prepared (tailored resume, cover letter), the
    same files the extension attaches."""
    if not file:
        return None
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(file["url"])
    if response.status_code != 200:
        logger.warning("Couldn't download %s (%s)", file["filename"], response.status_code)
        return None
    logger.info("Attaching %s (%d KB)", file["filename"], len(response.content) // 1024)
    return {"name": file["filename"], "type": file["content_type"],
            "base64": base64.b64encode(response.content).decode()}


async def _fill(page, payload: dict, files: dict) -> dict:
    """Run the extension's filler on the open form and return what it did."""
    # Wrapped in a function so Playwright runs the filler rather than
    # trying to read it as one.
    await page.evaluate("() => {" + FILLER_PATH.read_text() + "}")
    await page.evaluate(
        "([application, files]) => window.postMessage("
        "{ jobHunt: 'to-page', type: 'fill', application, resume: files.resume, coverLetter: files.coverLetter },"
        " location.origin)",
        [payload, files],
    )
    await page.wait_for_function("window.__jobHuntResult !== undefined", timeout=FILL_TIMEOUT_MS)
    await page.evaluate(HIDE_PANEL)
    return await page.evaluate("window.__jobHuntResult")


async def _submit_button(page):
    """The form's Submit button, found by what it says. Finding it by its
    place among the visible buttons ("the 19th") failed on Greenhouse: the
    list changes as the page scrolls, so each look found a different button
    and it never held still long enough to press."""
    buttons = page.get_by_role("button", name=SUBMIT_LABEL).filter(visible=True)
    if not await buttons.count():
        return None, None
    button = buttons.first
    label = ((await button.inner_text()) or (await button.get_attribute("value")) or "").strip()
    return button, label


async def _can_press(button) -> bool:
    """Whether the button can be pressed: Playwright's checks (on screen,
    enabled, still, nothing on top of it) without pressing it."""
    try:
        await button.scroll_into_view_if_needed(timeout=PRESS_TIMEOUT_MS)
        await button.click(trial=True, timeout=PRESS_TIMEOUT_MS)
        return True
    except Exception as e:  # noqa: BLE001 — reported to the user as "couldn't press Submit"
        logger.warning("Can't press the Submit button: %s", str(e).splitlines()[0])
        return False


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


# What each outcome means for the user, in plain words.
OUTCOME_MESSAGES = {
    "submitted": "Sent. The company's form confirmed it.",
    "dry_run": "Practice run done. Everything was filled in, and nothing was sent.",
    "incomplete": "Some questions couldn't be filled in, so nothing was sent.",
    "no_submit_button": "The app couldn't find the form's Submit button, so nothing was sent.",
    "cant_press_submit": (
        "Everything was filled in, but the app couldn't press the form's Submit button, so nothing was sent."
    ),
    "human_check": (
        "The form asked to check you're a person. The app doesn't get around that, so it stopped. "
        "Send this one with the extension, or by hand."
    ),
    "no_confirmation": (
        "The app pressed Submit but didn't see a confirmation. Check your email for one from the "
        "company before sending it again."
    ),
    "error": "Something went wrong on the company's form, so nothing was sent.",
}


async def _run_form(payload: dict, *, dry_run: bool) -> tuple[dict, bytes | None]:
    """Open the form, fill it in and (unless dry_run) submit it. Returns
    what happened and a screenshot of the page at the end."""
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 1600})
        page = await context.new_page()
        try:
            files = {
                "resume": await _attachment(payload.get("resume")),
                "coverLetter": await _attachment(payload.get("cover_letter")),
            }
            logger.info("Opening %s", payload["form_url"])
            try:
                outcome = await _fill_and_press(page, payload, files, dry_run=dry_run)
            except Exception as e:  # noqa: BLE001 — recorded for the user, with a picture of the page
                logger.exception("Filling in the form failed")
                outcome = {"status": "error", "detail": f"{type(e).__name__}: {e}"[:300], "url": page.url}
            try:
                screenshot = await page.screenshot(full_page=True)
            except Exception as e:  # noqa: BLE001 — the outcome counts without its picture
                logger.warning("Couldn't take a picture of the form: %s", e)
                screenshot = None
        finally:
            await context.close()
            await browser.close()
    return outcome, screenshot


async def _fill_and_press(page, payload: dict, files: dict, *, dry_run: bool) -> dict:
    await page.goto(payload["form_url"], wait_until="domcontentloaded", timeout=60_000)
    filled = await _fill(page, payload, files)
    missing = [item for item in filled["items"] if item["status"] == "todo"]
    logger.info("Filled in %d answers; %d need a person", filled["filled"], len(missing))
    for item in missing:
        logger.info("  not filled in: %s (%s)", item["label"][:70], item["note"])
    outcome = {"filled": filled["filled"], "not_filled": missing, "url": page.url}
    if missing:
        outcome["status"] = "incomplete"
        return outcome

    # A practice run goes as far as checking Submit can be pressed.
    button, label = await _submit_button(page)
    if button is None:
        outcome["status"] = "no_submit_button"
    elif not await _can_press(button):
        outcome["status"] = "cant_press_submit"
    elif dry_run:
        outcome["status"] = "dry_run"
    else:
        logger.info("Pressing %r", label)
        try:
            # Returns once the press is made; what the form does next is
            # watched below.
            await button.click(no_wait_after=True, timeout=PRESS_TIMEOUT_MS)
        except Exception as e:  # noqa: BLE001
            # The checks above had just passed, so this is unlikely, and
            # whether the press landed can't be known. Watching the page
            # tells: a confirmation means sent, anything else says to look
            # for the company's email before trying again.
            logger.warning("Pressing Submit raised: %s", str(e).splitlines()[0])
        outcome["status"] = await _watch_after_submit(page)
        outcome["url"] = page.url
    return outcome


async def _keep_screenshot(application: AutoApplication, what: str, content: bytes | None) -> str | None:
    if not content:
        return None
    from app.services.storage import upload_file

    path = f"applications/{application.user_id}/{application.id}-{what}.png"
    try:
        await upload_file("resumes", path, content, "image/png")
        return path
    except Exception as e:  # noqa: BLE001 — the outcome still counts without its picture
        logger.warning("Couldn't keep the screenshot for %s: %s", application.id, e)
        return None


async def send_application(application_id: uuid.UUID, *, dry_run: bool, claimed: bool = False) -> dict:
    """Fill in (and unless dry_run, send) one approved application, and
    record what happened on it: `result["practice"]` for a practice run,
    `result["send"]` for a real one. `claimed` is for requests from the app,
    already marked as being sent."""
    session = create_worker_session()
    async with session() as db:
        application = await db.get(AutoApplication, application_id)
        if application is None:
            raise SendRefused("No such application")
        if application.status == "submitted":
            raise SendRefused("This application was already sent")
        expected = "submitting" if claimed and not dry_run else "queued"
        if application.status != expected:
            raise SendRefused(f"The answers aren't approved yet (status: {application.status})")
        payload = await fill_details(db, application)
        if not payload.get("form_url"):
            raise SendRefused("This application has no form to fill in")

        try:
            outcome, screenshot = await _run_form(payload, dry_run=dry_run)
        except Exception as e:  # noqa: BLE001 — recorded for the user, never left half-sent
            logger.exception("Filling in the form failed for %s", application_id)
            outcome, screenshot = {"status": "error", "detail": f"{type(e).__name__}: {e}"[:300]}, None

        what = "practice" if dry_run else "send"
        outcome["at"] = datetime.now(timezone.utc).isoformat()
        outcome["message"] = OUTCOME_MESSAGES.get(outcome["status"], outcome["status"])
        outcome["screenshot"] = await _keep_screenshot(application, what, screenshot)
        result = {k: v for k, v in (application.result or {}).items() if k not in ("request", "running")}
        result[what] = outcome
        application.result = result

        if outcome["status"] == "submitted":
            application.error = None
            await mark_sent(db, application)
        else:
            if not dry_run:
                application.status = "queued"  # still approved; the user can try another way
                application.error = outcome["message"]
            await db.commit()
    return outcome


STALE_RUN_MINUTES = 20
STOPPED_MESSAGE = (
    "The last try stopped before it finished. Check your email for a confirmation from the company "
    "before sending it again."
)


def _without_run(result: dict | None) -> dict:
    return {k: v for k, v in (result or {}).items() if k not in ("request", "running")}


async def run_requested(limit: int = 3, send=None, now: datetime | None = None) -> list[dict]:
    """Send (or practise) the applications the user asked the app to send,
    oldest request first. Each is claimed before it runs (its request moves
    to "running"), so a run that overlaps another never takes it twice. A
    run that stopped halfway is let go after STALE_RUN_MINUTES."""
    from datetime import timedelta

    from sqlalchemy import select

    send = send or send_application
    now = now or datetime.now(timezone.utc)
    session = create_worker_session()
    async with session() as db:
        running = (await db.execute(
            select(AutoApplication).where(AutoApplication.result.has_key("running"))
        )).scalars().all()
        for application in running:
            started = datetime.fromisoformat(application.result["running"].get("started") or now.isoformat())
            if started < now - timedelta(minutes=STALE_RUN_MINUTES):
                application.result = _without_run(application.result)
                if application.status == "submitting":
                    application.status = "queued"
                    application.error = STOPPED_MESSAGE
        await db.commit()

        pending = (await db.execute(
            select(AutoApplication)
            .where(AutoApplication.status == "queued", AutoApplication.result.has_key("request"))
            .order_by(AutoApplication.updated_at)
            .limit(limit)
        )).scalars().all()
        claimed = []
        for application in pending:
            request = (application.result or {}).get("request") or {}
            practice = bool(request.get("practice"))
            if not practice:
                application.status = "submitting"
            application.result = {**_without_run(application.result), "running": {**request, "started": now.isoformat()}}
            claimed.append((application.id, practice))
        await db.commit()

    outcomes = []
    for application_id, practice in claimed:
        try:
            outcomes.append(await send(application_id, dry_run=practice, claimed=True))
        except SendRefused as e:
            logger.info("Not sending %s: %s", application_id, e)
            async with session() as db:
                application = await db.get(AutoApplication, application_id)
                if application is not None:
                    application.result = _without_run(application.result)
                    if application.status == "submitting":
                        application.status = "queued"
                    await db.commit()
    return outcomes


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
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("application_id", nargs="?", default=os.environ.get("SEND_APPLICATION_ID"))
    parser.add_argument("--dry-run", action="store_true", default=os.environ.get("SEND_DRY_RUN") == "true")
    args = parser.parse_args()
    if not args.application_id:
        # Every few minutes on a schedule: send what users asked to send.
        outcomes = asyncio.run(run_requested())
        logger.info("Sent or practised %d requested applications: %s", len(outcomes),
                    [o.get("status") for o in outcomes] or "none waiting")
        return
    try:
        outcome = asyncio.run(send_application(uuid.UUID(args.application_id), dry_run=args.dry_run))
    except SendRefused as e:
        # A refusal is an answer, not a failure: say it and stop cleanly.
        logger.info("Not sending: %s", e)
        return
    logger.info("Outcome: %s", json.dumps(outcome)[:2000])


if __name__ == "__main__":
    main()
