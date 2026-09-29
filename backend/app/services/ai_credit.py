"""What the app spends on Claude, and how long the credit will last.

Every call is added up per hour, task and model (`record_usage`, called by
llm/client.py for every call, including the ones that build their own
requests). Anthropic's API doesn't say what's left on the account, so the
admin records the balance shown on Anthropic's billing page after topping
up, and the app counts down from there. The counts are estimates from list
prices: Anthropic's billing page is the real figure.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.ai_usage import AiCreditBalance, AiUsageHour

logger = logging.getLogger(__name__)

# USD per million tokens (input, output), from Anthropic's pricing page on
# 2026-09-29. Cache writes cost 1.25x input, cache reads 0.1x.
PRICES_PER_MILLION = {
    "claude-haiku-4-5": (Decimal("1"), Decimal("5")),
    "claude-sonnet-5": (Decimal("2"), Decimal("10")),
    "claude-opus-5": (Decimal("5"), Decimal("25")),
}
UNKNOWN_MODEL_PRICE = PRICES_PER_MILLION["claude-opus-5"]  # count high rather than low
WEB_SEARCH_USD = Decimal("0.01")

# Warn once what's left is below this, or would last under WARN_DAYS.
LOW_BALANCE_USD = Decimal("1.00")
WARN_DAYS = 2
# Automatic preparing stops below this, so what's left goes to what people ask for.
RESERVE_USD = Decimal("0.50")

# What each task is, in words the admin reads.
TASK_NAMES = {
    "extraction": "Reading new jobs",
    "parsing": "Reading resumes and job pages",
    "scoring": "Job reviews",
    "search": "Searching the web",
    "tailoring": "Writing resumes and messages",
    "applying": "Answering application questions",
    "review": "Checking the writing",
    "job_search": "Searching the web for jobs",
    "apply_link": "Finding where to apply",
    "contact": "Finding a person to contact",
    "translation": "Translating jobs",
}


def task_name(task: str) -> str:
    return TASK_NAMES.get(task, task.replace("_", " ").capitalize())


def _prices(model: str) -> tuple[Decimal, Decimal]:
    for name, prices in PRICES_PER_MILLION.items():
        if model.startswith(name):
            return prices
    return UNKNOWN_MODEL_PRICE


def _count(value) -> int:
    return value if isinstance(value, int) else 0


def web_searches(usage) -> int:
    return _count(getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0))


def call_cost(model: str, usage) -> Decimal:
    """What one call cost, from its usage and the list price."""
    input_price, output_price = _prices(model)
    tokens = (
        _count(usage.input_tokens) * input_price
        + _count(getattr(usage, "cache_creation_input_tokens", 0)) * input_price * Decimal("1.25")
        + _count(getattr(usage, "cache_read_input_tokens", 0)) * input_price * Decimal("0.1")
        + _count(usage.output_tokens) * output_price
    )
    return tokens / Decimal(1_000_000) + web_searches(usage) * WEB_SEARCH_USD


async def record_usage(task: str, model: str, usage, *, session_factory=None) -> None:
    """Add one call to its hour's total. Never raises: a call that worked
    must not fail because it couldn't be counted."""
    try:
        if session_factory is None:
            from app.core.database import async_session as session_factory
        hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        row = {
            "hour": hour, "task": task[:40], "model": model[:60], "calls": 1,
            "input_tokens": _count(usage.input_tokens), "output_tokens": _count(usage.output_tokens),
            "web_searches": web_searches(usage), "cost_usd": call_cost(model, usage),
        }
        statement = pg_insert(AiUsageHour).values(**row)
        statement = statement.on_conflict_do_update(
            index_elements=["hour", "task", "model"],
            set_={
                name: getattr(AiUsageHour, name) + getattr(statement.excluded, name)
                for name in ("calls", "input_tokens", "output_tokens", "web_searches", "cost_usd")
            },
        )
        async with session_factory() as db:
            await db.execute(statement)
            await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("Couldn't count an AI call (%s): %s", task, e)


def _money(value: Decimal | float | None) -> float | None:
    return None if value is None else round(float(value), 2)


async def latest_balance(db) -> AiCreditBalance | None:
    return (await db.execute(
        select(AiCreditBalance).order_by(AiCreditBalance.recorded_at.desc()).limit(1)
    )).scalar_one_or_none()


async def record_balance(db, amount: Decimal, user_id=None) -> AiCreditBalance:
    balance = AiCreditBalance(balance_usd=amount, recorded_by=user_id)
    db.add(balance)
    await db.commit()
    return balance


async def spent_since(db, since: datetime) -> Decimal:
    # Whole hours: the hour the balance was read in counts in full, so the
    # estimate errs towards less left, never more.
    start = since.replace(minute=0, second=0, microsecond=0)
    return (await db.execute(
        select(func.coalesce(func.sum(AiUsageHour.cost_usd), 0)).where(AiUsageHour.hour >= start)
    )).scalar() or Decimal(0)


async def credit_left(db) -> Decimal | None:
    """The estimated balance, or None when no balance has been recorded."""
    balance = await latest_balance(db)
    if balance is None:
        return None
    return balance.balance_usd - await spent_since(db, balance.recorded_at)


async def credit_status(db, *, now: datetime | None = None, days: int = 7) -> dict:
    """Spending by day and task, and what's left if a balance was recorded."""
    from app.llm.client import CREDITS_MESSAGE, credits_paused

    now = now or datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    first_day = today - timedelta(days=days - 1)
    # Days in UTC, whatever the database session's time zone is.
    day = func.date_trunc("day", AiUsageHour.hour, "UTC")
    rows = (await db.execute(
        select(day, AiUsageHour.task, func.sum(AiUsageHour.cost_usd), func.sum(AiUsageHour.calls))
        .where(AiUsageHour.hour >= first_day)
        .group_by(day, AiUsageHour.task)
    )).all()

    by_day: dict[str, dict] = {}
    for when, task, cost, calls in rows:
        key = when.astimezone(timezone.utc).date().isoformat()
        entry = by_day.setdefault(key, {"day": key, "total": Decimal(0), "tasks": []})
        entry["total"] += cost
        entry["tasks"].append({"task": task, "name": task_name(task), "cost": _money(cost), "calls": int(calls)})
    listed = []
    for offset in range(days):
        key = (first_day + timedelta(days=offset)).date().isoformat()
        entry = by_day.get(key, {"day": key, "total": Decimal(0), "tasks": []})
        entry["tasks"].sort(key=lambda t: -(t["cost"] or 0))
        listed.append(entry)

    # The last three whole days, or today alone when that's all there is.
    whole_days = [e["total"] for e in listed[-4:-1] if e["total"] > 0]
    per_day = sum(whole_days) / len(whole_days) if whole_days else listed[-1]["total"] or None

    balance = await latest_balance(db)
    left = days_left = None
    if balance is not None:
        left = balance.balance_usd - await spent_since(db, balance.recorded_at)
        if per_day:
            days_left = max(Decimal(0), left) / per_day

    paused = credits_paused()
    low = left is not None and (left < LOW_BALANCE_USD or (days_left is not None and days_left < WARN_DAYS))
    warning = None
    if paused:
        warning = CREDITS_MESSAGE
    elif low:
        warning = (
            f"About ${max(Decimal(0), left):.2f} of AI credit is left"
            + (f", about {_days(days_left)} at the current rate" if days_left is not None else "")
            + ". Top up on Anthropic's billing page, then record the new balance here."
        )

    return {
        "paused": paused,
        "low": low,
        "warning": warning,
        "balance": {"amount": _money(balance.balance_usd), "recorded_at": balance.recorded_at.isoformat()} if balance else None,
        "left": _money(left),
        "per_day": _money(per_day),
        "days_left": round(float(days_left), 1) if days_left is not None else None,
        "days": [{**e, "total": _money(e["total"])} for e in listed],
    }


def _days(days: Decimal) -> str:
    if days < 1:
        return "less than a day"
    whole = int(days)
    return "1 day" if whole == 1 else f"{whole} days"
