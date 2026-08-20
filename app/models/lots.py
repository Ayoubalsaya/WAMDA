from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import LotStatus, lot_status_enum


class CurrencyLot(Base):
    """§3-6. cost_rate/original_qty يُجمَّدان بعد أول استهلاك — يُفرض بالتطبيق (منطق الترحيل)."""

    __tablename__ = "currency_lots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lot_no: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # LOT-2026-0001
    source_entry_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("journal_entries.id"), nullable=False)
    currency_code: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), nullable=False)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"), nullable=False)
    original_qty: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    remaining_qty: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    cost_rate: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    cost_total: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    cost_currency: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[LotStatus] = mapped_column(lot_status_enum, nullable=False, default=LotStatus.OPEN)

    __table_args__ = (
        CheckConstraint("original_qty > 0", name="ck_lots_original_positive"),
        CheckConstraint("remaining_qty >= 0", name="ck_lots_remaining_nonneg"),
        CheckConstraint("remaining_qty <= original_qty", name="ck_lots_remaining_le_original"),
        Index("ix_lots_ccy_status_opened", "currency_code", "status", "opened_at"),
    )


class LotConsumption(Base):
    __tablename__ = "lot_consumptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lot_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("currency_lots.id"), nullable=False)
    entry_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("journal_entries.id"), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    client_rate: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    cost_share: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    revenue: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    profit: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    profit_currency: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_lot_consumptions_qty_positive"),
        Index("ix_lot_consumptions_lot", "lot_id"),
        Index("ix_lot_consumptions_entry", "entry_id"),
    )
