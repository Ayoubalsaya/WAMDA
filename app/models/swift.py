from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import SwiftStatus, swift_status_enum


class SwiftMovement(Base):
    """§3-5. سجل حالة وتجميع فقط — ليس مصدر حقيقة مالياً. external_ref غير مالي."""

    __tablename__ = "swift_movements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    out_entry_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("journal_entries.id"))
    in_entry_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("journal_entries.id"))
    return_entry_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("journal_entries.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency_code: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), nullable=False)
    transfer_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    received_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    received_date: Mapped[Optional[datetime]] = mapped_column(Date)
    exchange_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 10))
    profit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    profit_currency: Mapped[Optional[str]] = mapped_column(Text, ForeignKey("currencies.code"))
    external_ref: Mapped[Optional[str]] = mapped_column(Text)  # تشغيلي غير مالي — لا يدخل أي تقرير
    status: Mapped[SwiftStatus] = mapped_column(swift_status_enum, nullable=False, default=SwiftStatus.SENT)
