from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import EntryStatus, OperationType, entry_status_enum, operation_type_enum


class JournalEntry(Base):
    """§3-4. حالة الإدخال تمر دائماً DRAFT → POSTED — يُفرض بمشغّل DB (انظر الترحيل)."""

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entry_no: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # WMD-2026-000001
    entry_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    operation_type: Mapped[OperationType] = mapped_column(operation_type_enum, nullable=False)
    client_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("clients.id"))
    partner_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("partners.id"))
    from_currency: Mapped[Optional[str]] = mapped_column(Text, ForeignKey("currencies.code"))
    to_currency: Mapped[Optional[str]] = mapped_column(Text, ForeignKey("currencies.code"))
    cost_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 10))
    client_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 10))
    profit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6))  # مشتق لا مُدخل
    profit_currency: Mapped[Optional[str]] = mapped_column(Text, ForeignKey("currencies.code"))
    is_backdated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    backdate_reason: Mapped[Optional[str]] = mapped_column(Text)
    negative_margin_reason: Mapped[Optional[str]] = mapped_column(Text)
    outage_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    real_operation_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    chain_ref: Mapped[Optional[str]] = mapped_column(Text)
    chain_seq: Mapped[Optional[int]] = mapped_column(SmallInteger)
    chain_total: Mapped[Optional[int]] = mapped_column(SmallInteger)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # ملاحظة يكتبها المُدخِل وقت إنشاء العملية — بخلاف description (نص
    # داخلي مولَّد تلقائياً، مثل "عكس WMD-... : السبب" في reverse_entry).
    # تظهر في: الإيصال · كشف الحساب · تفاصيل القيد · عمليات اليوم.
    note: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[EntryStatus] = mapped_column(entry_status_enum, nullable=False, default=EntryStatus.DRAFT)
    reverses_entry_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("journal_entries.id"))
    reversed_by_entry_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("journal_entries.id"))
    # يربط قيداً جديداً بالقيد الأصلي الذي حلّ محلّه عبر "تعديل" (عكس +
    # إنشاء جديد، §٥ قاعدة ٢) — يفرّق بصرياً بين "إلغاء بلا بديل" (الأصل
    # REVERSED بلا replaces وارد إليه) و"تعديل" (قيد جديد يحمل replaces_entry_id
    # يشير للأصل)، فتُعرَض العملية المعدَّلة كصفّ واحد بشارة تفتح السجل
    # الكامل بدل ظهورها مرتين.
    replaces_entry_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("journal_entries.id"))
    correction_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    posted_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"))
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # §6 القيود الثلاثة: قيد لا يحمل client_id و partner_id معاً — الطرف
        # الآخر لأي قيد هو دائماً حساب شركة داخلي لا "شريك ثانٍ" في نفس القيد.
        CheckConstraint(
            "NOT (client_id IS NOT NULL AND partner_id IS NOT NULL)",
            name="ck_journal_entries_client_xor_partner",
        ),
        Index("ix_je_entry_date", "entry_date"),
        Index("ix_je_client", "client_id"),
        Index("ix_je_partner", "partner_id"),
        Index("ix_je_created_by", "created_by"),
        Index("ix_je_chain_ref", "chain_ref"),
        Index("ix_je_replaces_entry_id", "replaces_entry_id"),
    )


class JournalLine(Base):
    """§3-4. عدم القابلية للتعديل بعد POSTED + مطابقة العملة يُفرضان بمشغّلات DB."""

    __tablename__ = "journal_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entry_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("journal_entries.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"), nullable=False)
    currency_code: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), nullable=False)
    debit: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    memo: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("debit >= 0", name="ck_journal_lines_debit_nonneg"),
        CheckConstraint("credit >= 0", name="ck_journal_lines_credit_nonneg"),
        CheckConstraint("NOT (debit <> 0 AND credit <> 0)", name="ck_journal_lines_one_side"),
        UniqueConstraint("entry_id", "line_no", name="uq_journal_lines_entry_line"),
        Index("ix_jl_account_entry", "account_id", "entry_id"),
    )


class EntryComment(Base):
    """تعليق لاحق على قيد — append-only، بخلاف `note` (تُكتب وقت الإدخال
    وتظهر في الإيصال). التعليقات لا تظهر إطلاقاً في إيصال مطبوع سابقاً
    (الإيصال وثيقة بتاريخها) — فقط في تفاصيل القيد وكشف الحساب الداخلي.
    لا تعديل ولا حذف — أي كتابة هنا تُسجَّل في audit_log (§٥ قاعدة ١١).
    """

    __tablename__ = "entry_comments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entry_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("journal_entries.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_entry_comments_entry", "entry_id"),
    )
