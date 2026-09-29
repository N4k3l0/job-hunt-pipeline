"""What the app spends on Claude, so the admin can see it and be warned
before the credit runs out. Anthropic's API doesn't say what's left on the
account, so the admin records the balance after topping up and the app
counts down from there (services/ai_credit.py)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AiUsageHour(Base):
    """Every call in one hour for one task and model, added up."""

    __tablename__ = "ai_usage_hours"

    hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    task: Mapped[str] = mapped_column(String(40), primary_key=True)
    model: Mapped[str] = mapped_column(String(60), primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    web_searches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)


class AiCreditBalance(Base):
    """The account balance the admin read on Anthropic's billing page."""

    __tablename__ = "ai_credit_balances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    balance_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
