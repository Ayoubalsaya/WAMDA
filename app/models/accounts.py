from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import AccountForm, AccountType, account_form_enum, account_type_enum


class Account(Base):
    """§3-2 — شجرة الحسابات.

    ⚠ تعديل عن مسودة الـDDL السابقة: currency_code أصبح NULLABLE.
    السبب: حسابات التجميع/الرؤوس (1000, 1100, 1300, 2100, 3000 ...) لا
    عملة طبيعية لها — وهذا يطابق فقرة §3-2 الأصلية بالوثيقة التي لم تكن
    تضع NOT NULL على العمود أصلاً. الحسابات القابلة للترحيل (leaf) تحمل
    عملة حقيقية دائماً؛ التمييز يُفرض بالتطبيق لا بقيد DB إضافي غير موصوف.
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[AccountType] = mapped_column(account_type_enum, nullable=False)
    currency_code: Mapped[Optional[str]] = mapped_column(Text, ForeignKey("currencies.code"))
    location_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("locations.id"))
    form: Mapped[Optional[AccountForm]] = mapped_column(account_form_enum)
    parent_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("accounts.id"))
    client_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("clients.id"))
    partner_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("partners.id"))
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        # §2-2 القاعدة الفاصلة: لا رصيد عميل مربوط بشركة مراسلة بعينها
        CheckConstraint(
            "NOT (client_id IS NOT NULL AND partner_id IS NOT NULL)",
            name="ck_accounts_client_xor_partner",
        ),
        Index("ix_accounts_client", "client_id", postgresql_where=text("client_id IS NOT NULL")),
        Index("ix_accounts_partner", "partner_id", postgresql_where=text("partner_id IS NOT NULL")),
        Index("ix_accounts_parent", "parent_id"),
        Index("ix_accounts_type_ccy_loc", "type", "currency_code", "location_id"),
    )


class AccountNumberCounter(Base):
    """§3-2 — ترقيم الحسابات الفرعية للعملات تحت أب واحد (idempotent، قفل صفّي)."""

    __tablename__ = "account_number_counters"

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"), primary_key=True)
    next_suffix: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AccountNumberAssignment(Base):
    __tablename__ = "account_number_assignments"

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"), primary_key=True)
    currency_code: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), primary_key=True)
    assigned_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
