from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Partner(Base):
    """§3-3 — مكاتب ليبيا + شركات تركيا معاً."""

    __tablename__ = "partners"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(Text)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    contact_phone: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Client(Base):
    """§3-3. search_name تُملأ آلياً بمشغّل DB — §3-9."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(Text)
    id_number: Mapped[Optional[str]] = mapped_column(Text)
    search_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    credit_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # ⚠ clients.credit_limit حُذف — انظر ClientCreditLimit أدناه (حد لكل عملة).
    portal_password_hash: Mapped[Optional[str]] = mapped_column(Text)
    portal_must_change: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    portal_security_question: Mapped[Optional[str]] = mapped_column(Text)
    portal_security_answer_hash: Mapped[Optional[str]] = mapped_column(Text)
    portal_failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    portal_locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"))


class ClientCreditLimit(Base):
    """حد ائتمان لكل عميل × عملة (لا تحويل بين العملات في أي فحص — §2-3)."""

    __tablename__ = "client_credit_limits"

    client_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clients.id"), primary_key=True)
    currency_code: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), primary_key=True)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)

    __table_args__ = (
        CheckConstraint("limit_amount >= 0", name="ck_client_credit_limits_nonneg"),
    )


class Beneficiary(Base):
    __tablename__ = "beneficiaries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clients.id"), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    account_number: Mapped[str] = mapped_column(Text, nullable=False)  # إلزامي — اختبار القبول ٣٢
    bank_name: Mapped[Optional[str]] = mapped_column(Text)
    currency_code: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), nullable=False)
    purpose: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)  # تعطيل فقط، لا حذف


class RemitOutDestination(Base):
    """لقطة لحظة الترحيل — §3-3. لا تتأثر بتعديل المستفيد لاحقاً (اختبار القبول ٣٣)."""

    __tablename__ = "remit_out_destinations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entry_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("journal_entries.id"), unique=True, nullable=False)
    beneficiary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("beneficiaries.id"), nullable=False)
    beneficiary_name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    account_number_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    bank_name_snapshot: Mapped[Optional[str]] = mapped_column(Text)
    currency_code: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
