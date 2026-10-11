"""What the app spends on Claude, against its monthly budget.

Every call is added up per hour, task and model (`record_usage`, called by
llm/client.py for every call, including the ones that build their own
requests). The Anthropic account can be shared with other products, so its
balance says nothing about Job Hunt: instead Job Hunt has a monthly budget
(`monthly_budget`, $15 to start, changed on the admin page) and counts its
own spending against it. Admins are warned as it gets close. At the budget,
background AI work (reading new jobs, preparing applications by itself)
waits for the next month; what a user asks for still runs. The counts are
estimates from list prices: Anthropic's console has the real figures.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.ai_usage import AiUsageHour

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

# The admin's change to the budget, kept with their settings.
BUDGET_KEY = "ai_monthly_budget_usd"
# Warn once this much of the budget is used, or the month is heading over it.
WARN_SHARE = Decimal("0.8")
# Automatic preparing stops this close to the budget, so what's left goes
# to what people ask for.
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


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def monthly_budget(db) -> Decimal:
    """The admin's budget, or the starting one from settings."""
    from app.core.config import get_settings
    from app.models.user import User

    stored = (await db.execute(
        select(User.preferences[BUDGET_KEY].astext).where(
            User.role == "admin", User.preferences[BUDGET_KEY].astext.is_not(None),
        ).limit(1)
    )).scalar()
    try:
        return Decimal(stored) if stored is not None else Decimal(str(get_settings().ai_monthly_budget_usd))
    except ArithmeticError:
        return Decimal(str(get_settings().ai_monthly_budget_usd))


async def set_monthly_budget(db, admin, amount: Decimal) -> None:
    from app.models.user import User

    # Loaded here, so the change is saved whatever session `admin` came from.
    user = await db.get(User, admin.id)
    user.preferences = {**(user.preferences or {}), BUDGET_KEY: str(amount)}
    await db.commit()


async def spent_this_month(db, now: datetime | None = None) -> Decimal:
    now = now or datetime.now(timezone.utc)
    return (await db.execute(
        select(func.coalesce(func.sum(AiUsageHour.cost_usd), 0)).where(AiUsageHour.hour >= _month_start(now))
    )).scalar() or Decimal(0)


async def budget_left(db, now: datetime | None = None) -> Decimal:
    """What's left of this month's budget; below zero once it's gone over."""
    return await monthly_budget(db) - await spent_this_month(db, now)


async def credit_status(db, *, now: datetime | None = None, days: int = 7) -> dict:
    """Spending by day and task, and this month against the budget."""
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

    budget = await monthly_budget(db)
    spent = await spent_this_month(db, now)
    next_month = (_month_start(now) + timedelta(days=32)).replace(day=1)
    days_to_go = Decimal((next_month - now).total_seconds()) / Decimal(86400)
    heading_for = spent + (per_day or 0) * days_to_go
    over = spent >= budget
    low = not over and (spent >= budget * WARN_SHARE or heading_for > budget)

    paused = credits_paused()
    warning = None
    if paused:
        warning = CREDITS_MESSAGE
    elif over:
        warning = (
            f"Job Hunt has used its ${budget:.2f} AI budget for this month (${spent:.2f}). Reading new jobs and "
            "preparing applications by itself wait for the 1st; what people ask for still works. You can raise "
            "the budget on the admin page."
        )
    elif low:
        warning = (
            f"Job Hunt has used ${spent:.2f} of its ${budget:.2f} AI budget this month"
            + (f", and at about ${per_day:.2f} a day it's heading for ${heading_for:.2f}" if per_day else "")
            + ". At the budget, reading new jobs and preparing applications by itself wait for the 1st."
        )

    return {
        "paused": paused,
        "low": low or over,
        "over": over,
        "warning": warning,
        "budget": _money(budget),
        "spent_this_month": _money(spent),
        "left": _money(budget - spent),
        "per_day": _money(per_day),
        "heading_for": _money(heading_for),
        "days": [{**e, "total": _money(e["total"])} for e in listed],
    }
