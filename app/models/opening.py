from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import (
    ConfidenceLevel,
    OpeningSourceType,
    ReconciliationStatus,
    confidence_level_enum,
    opening_source_type_enum,
    reconciliation_status_enum,
)


class OpeningBalance(Base):
    """§3-7. contra_account_id يُشتق آلياً من confidence: HIGH→3100.x · غير ذلك→3900.x."""

    __tablename__ = "opening_balances"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency_code: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), nullable=False)
    as_of_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    source_type: Mapped[OpeningSourceType] = mapped_column(opening_source_type_enum, nullable=False)
    source_note: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[ConfidenceLevel] = mapped_column(confidence_level_enum, nullable=False)
    contra_account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"), nullable=False)
    approved_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OpeningReconciliation(Base):
    __tablename__ = "opening_reconciliation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"), nullable=False)
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    verified_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    difference: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency_code: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReconciliationStatus] = mapped_column(
        reconciliation_status_enum, nullable=False, default=ReconciliationStatus.OPEN
    )
    resolving_entry_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("journal_entries.id"))
    approved_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
