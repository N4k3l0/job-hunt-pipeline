"""Scheduled work, run by the Railway "scheduler" cron service every 30 minutes.

Each run calls the backend's cron endpoints in order:
- 06:00–06:29 UTC: discover jobs from company boards and job APIs
- 06:30–06:59 UTC: discover jobs from remote-work job boards
- every run: read new jobs with Claude, find full postings for jobs from
  LinkedIn alert emails, expire closed jobs, send the daily email (once a
  day per user, from DIGEST_HOUR_UTC on the backend), and (when
  REVIEWS_PER_USER_PER_DAY is above 0) review each user's best new matches

Environment:
    BACKEND_URL               e.g. https://backend-production-7e805.up.railway.app
    CRON_SECRET               the backend's cron secret
    ENRICH_JOBS_PER_RUN       jobs read per run (default 25)
    REVIEWS_PER_USER_PER_DAY  AI reviews per user per day (default 0: off)

`--discovery fast|remote|both` runs discovery now regardless of the time.
Exits non-zero if any step failed, so Railway marks the run as failed.
Standard library only: runs in any Python 3.10+ image.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DISCOVERY_TIMEOUT = 300
TASK_TIMEOUT = 180


def call(base_url: str, secret: str, path: str, timeout: int) -> bool:
    started = time.monotonic()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {secret}", "User-Agent": "job-hunt-scheduler"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            ok = True
    except urllib.error.HTTPError as e:
        body = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}"
        ok = False
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        body = f"{type(e).__name__}: {e}"
        ok = False
    elapsed = time.monotonic() - started
    try:
        body = json.dumps(json.loads(body))[:2000]
    except ValueError:
        body = body[:2000]
    print(f"[{'ok' if ok else 'FAILED'}] {path.split('?')[0]} in {elapsed:.1f}s: {body}", flush=True)
    return ok


def discovery_due(now: datetime) -> list[str]:
    if now.hour != 6:
        return []
    return ["fast"] if now.minute < 30 else ["remote"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--discovery", choices=["fast", "remote", "both"])
    args = parser.parse_args()

    base_url = os.environ.get("BACKEND_URL", "").strip()
    secret = os.environ.get("CRON_SECRET", "").strip()
    if not base_url or not secret:
        print("BACKEND_URL and CRON_SECRET must be set", file=sys.stderr)
        return 2
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"
    jobs_per_run = int(os.environ.get("ENRICH_JOBS_PER_RUN") or 25)
    reviews = int(os.environ.get("REVIEWS_PER_USER_PER_DAY") or 0)

    now = datetime.now(timezone.utc)
    if args.discovery == "both":
        discovery = ["fast", "remote"]
    elif args.discovery:
        discovery = [args.discovery]
    else:
        discovery = discovery_due(now)
    print(f"Scheduled run at {now.isoformat(timespec='seconds')}; discovery: {discovery or 'none'}", flush=True)

    results = []
    for kind in discovery:
        results.append(call(base_url, secret, f"/api/v1/cron/discover-{kind}", DISCOVERY_TIMEOUT))
    results.append(call(base_url, secret, f"/api/v1/cron/enrich?limit={jobs_per_run}", TASK_TIMEOUT))
    results.append(call(base_url, secret, "/api/v1/cron/job-alert-details?limit=10", TASK_TIMEOUT))
    results.append(call(base_url, secret, "/api/v1/cron/expire-stale?verify_limit=40", TASK_TIMEOUT))
    results.append(call(base_url, secret, "/api/v1/cron/send-digests", TASK_TIMEOUT))
    # After a scoring change, users whose scores are from the old version
    # are rescored a couple at a time until none are left.
    results.append(call(base_url, secret, "/api/v1/cron/rescore-outdated?max_users=2", TASK_TIMEOUT))
    if reviews > 0:
        results.append(call(
            base_url, secret, f"/api/v1/cron/review-top-matches?per_user_daily={reviews}", TASK_TIMEOUT,
        ))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
