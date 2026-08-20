from datetime import datetime
from typing import Optional

from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import (
    EditRequestStatus,
    ReconciliationStatus,
    SessionSubjectType,
    edit_request_status_enum,
    reconciliation_status_enum,
    session_subject_type_enum,
)

# §7-13 / §9: الأدوار "مغلقة" اليوم لكن قد يُضاف دور ثالث لاحقاً (مراجع/محدود)
# — لذلك CHECK نصّي لا ENUM، بخلاف بقية المجموعات المغلقة صراحة في الوثيقة.
USER_ROLES = ("ADMIN", "ACCOUNTANT")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    security_question: Mapped[Optional[str]] = mapped_column(Text)
    security_answer_hash: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    totp_secret: Mapped[Optional[str]] = mapped_column(Text)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"role IN {USER_ROLES}", name="ck_users_role"),
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    subject_type: Mapped[SessionSubjectType] = mapped_column(
        session_subject_type_enum, nullable=False
    )
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # لا FK صلب — تعدد أشكال USER/CLIENT
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip: Mapped[Optional[str]] = mapped_column(INET)
    ua: Mapped[Optional[str]] = mapped_column(Text)


class AuditLog(Base):
    """Append-only — يُفرض بمشغّل قاعدة بيانات، انظر الترحيل."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # توسعة معتمدة على الوثيقة: actor_type/actor_id بدل user_id فقط،
    # لتغطية كتابات العميل في البوابة (لا صف users له).
    actor_type: Mapped[SessionSubjectType] = mapped_column(session_subject_type_enum, nullable=False)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    before_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    after_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    ip: Mapped[Optional[str]] = mapped_column(INET)
    request_id: Mapped[Optional[str]] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Period(Base):
    __tablename__ = "periods"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    closed_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("month BETWEEN 1 AND 12", name="ck_periods_month"),)


class FoundingPeriod(Base):
    """صف وحيد (singleton) — لا مفتاح طبيعي في الوثيقة."""

    __tablename__ = "founding_period"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"))

    __table_args__ = (CheckConstraint("id = 1", name="ck_founding_period_singleton"),)


class OutageWindow(Base):
    __tablename__ = "outage_windows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    opened_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    closed_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"))
    note: Mapped[Optional[str]] = mapped_column(Text)


class Counter(Base):
    """entry_no / chain_ref / lot_no بلا فجوات — §5-9."""

    __tablename__ = "counters"

    name: Mapped[str] = mapped_column(Text, primary_key=True)  # 'WMD' | 'CHN' | 'LOT'
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)


class EditRequest(Base):
    __tablename__ = "edit_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entry_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("journal_entries.id"), nullable=False)
    requested_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[EditRequestStatus] = mapped_column(
        edit_request_status_enum, nullable=False, default=EditRequestStatus.PENDING
    )
    decided_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class PartnerStatement(Base):
    __tablename__ = "partner_statements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    partner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("partners.id"), nullable=False)
    period_from: Mapped[datetime] = mapped_column(Date, nullable=False)
    period_to: Mapped[datetime] = mapped_column(Date, nullable=False)
    file_ref: Mapped[Optional[str]] = mapped_column(Text)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PartnerStatementLine(Base):
    __tablename__ = "partner_statement_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    statement_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("partner_statements.id"), nullable=False)
    value_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    matched_entry_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("journal_entries.id"))
    status: Mapped[ReconciliationStatus] = mapped_column(
        reconciliation_status_enum, nullable=False, default=ReconciliationStatus.OPEN
    )


class AccountBalance(Base):
    """رصيد مشتق يُعاد بناؤه بالكامل — §3-8. لا تعديل يدوي."""

    __tablename__ = "account_balances"

    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"), primary_key=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(Text, primary_key=True)  # UUIDv4 من المتصفح — §6-4
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    response_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    entry_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("journal_entries.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
