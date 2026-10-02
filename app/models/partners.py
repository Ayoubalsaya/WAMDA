from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
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
    # ⚠ clients.credit_allowed حُذف (٢٠٢٦-١٠-٠٣، قرار مالك: ائتمان بلا سقف) — الائتمان لكل عملة في ClientCreditLimit.mode؛
    # حالة العميل (مفتوح/متوقف/جزئي) تُحسب منها (app/engine/credit.py). ⚠ clients.credit_limit حُذف قبلها.
    portal_password_hash: Mapped[Optional[str]] = mapped_column(Text)
    # ⚠ portal_must_change حُذف (٢٠٢٦-١٠-٠٢، قرار مالك — إدارة بوابة العميل):
    # لم يعد هناك مسار يُنشئ كلمة مرور نيابة عن العميل — العميل يختارها
    # بنفسه دوماً عبر قبول رابط الدعوة (`client_portal_invites`)، فلا توجد
    # حالة "كلمة مرور مفروضة يجب تغييرها أول دخول" بعد الآن.
    portal_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    portal_last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    portal_security_question: Mapped[Optional[str]] = mapped_column(Text)
    portal_security_answer_hash: Mapped[Optional[str]] = mapped_column(Text)
    portal_failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    portal_locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"))


class ClientPortalInvite(Base):
    """رابط دعوة لمرة واحدة يعيّن به العميل كلمة مروره بنفسه (§٧-٦ — إدارة
    بوابة العميل، ٢٠٢٦-١٠-٠٢). يُخزَّن `token_hash` (SHA-256) فقط — الرمز
    الخام لا يُخزَّن ولا يظهر إلا في رد إنشاء الدعوة مرة واحدة، ولا يُمرَّر
    أبداً في مسار/استعلام (`#invite=` في الواجهة، جسم الطلب في الـAPI) كي
    لا يظهر في أي سجل وصول خادم.

    لا حذف للصفوف (سياسة المشروع) — دعوة جديدة تُبطل القديمة (`revoked_at`)
    بدل حذفها؛ "الدعوة الحيّة" الحالية هي الأحدث بلا `used_at`/`revoked_at`."""

    __tablename__ = "client_portal_invites"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clients.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_client_portal_invites_client", "client_id"),
    )


class ClientCreditLimit(Base):
    """ائتمان لكل عميل × عملة (لا تحويل بين العملات في أي فحص — §2-3). الوضع صريح (٢٠٢٦-١٠-٠٣): NONE بلا ائتمان ·
    LIMIT حد بمبلغ (`limit_amount` مجمَّع عبر مواقع العميل) · UNLIMITED بلا سقف — **لا** يعني NULL شيئاً.
    غياب الصف = NONE (عملة تُضاف لاحقاً لا تُفعَّل تلقائياً)."""

    __tablename__ = "client_credit_limits"

    client_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clients.id"), primary_key=True)
    currency_code: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), primary_key=True)
    mode: Mapped[str] = mapped_column(Text, nullable=False, default="LIMIT", server_default="LIMIT")
    limit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)

    __table_args__ = (
        CheckConstraint("limit_amount IS NULL OR limit_amount >= 0", name="ck_client_credit_limits_nonneg"),
        CheckConstraint("mode IN ('NONE', 'LIMIT', 'UNLIMITED')", name="ck_client_credit_limits_mode"),
        CheckConstraint("(mode = 'LIMIT') = (limit_amount IS NOT NULL)", name="ck_client_credit_limits_limit_iff_limit_mode"),
    )


# Beneficiary/RemitOutDestination أُلغيا (قرار مالك ٢٠٢٦-٠٩-٢٢): ٩٥٪ من
# العملاء يعطون رقم حساب فقط بلا معلومة أخرى، وحقل ملاحظة العملية يكفي
# لتدوين الوجهة. انظر PROGRESS.md — المرحلة ١٤ج (إلغاء المستفيدين).
