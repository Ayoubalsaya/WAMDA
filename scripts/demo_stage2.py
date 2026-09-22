"""عرض المرحلة ٢: يشغّل محرك القيود فعلياً على القاعدة وينتج أمثلة §١-٣
الثلاثة (أ · ب · ج) بأسطرها الكاملة، للمراجعة قبل اعتماد المرحلة ٣.

ليس بذرة بيانات — الشركاء/العميل هنا بيانات تجريبية صريحة لغرض
العرض فقط (partner codes تبدأ بـ DEMO-)، ومستخدم النظام معطَّل ولا يصلح
لتسجيل دخول حقيقي؛ لا شيء هنا يُعاد استخدامه كبيانات تأسيسية فعلية.
"""

from __future__ import annotations

import sys
import uuid
from decimal import Decimal

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.engine import accounts_repo, clock
from app.engine.operations import cash_transfer, exchange, receipt, remit_out, swift_in, swift_out
from app.models import Account, Client, JournalLine, Partner, User
from app.models.enums import AccountForm, AccountType

WORK_TZ = settings.work_timezone


def _uuid() -> str:
    return str(uuid.uuid4())


def _ensure_demo_user(db) -> User:
    user = db.execute(select(User).where(User.username == "demo_stage2")).scalar_one_or_none()
    if user is not None:
        return user
    user = User(
        username="demo_stage2",
        full_name="حساب تجريبي — عرض محرك القيود (المرحلة ٢)",
        password_hash="DISABLED-NOT-FOR-LOGIN",
        role="ADMIN",
        is_active=False,  # معطَّل عمداً — ليس حساب دخول حقيقياً، فقط FK صالح للعرض
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    return user


def _ensure_partner_account(db, *, partner_code, partner_name, country, account_code, account_name, currency_code, location_code, parent_code) -> Account:
    existing = db.execute(select(Account).where(Account.code == account_code)).scalar_one_or_none()
    if existing is not None:
        return existing
    partner = db.execute(select(Partner).where(Partner.code == partner_code)).scalar_one_or_none()
    if partner is None:
        partner = Partner(code=partner_code, name_ar=partner_name, country=country)
        db.add(partner)
        db.flush()
    location = accounts_repo.get_location_by_code(db, location_code)
    parent = accounts_repo.get_account_by_code(db, parent_code)
    account = Account(
        code=account_code,
        name_ar=account_name,
        type=AccountType.ASSET,
        currency_code=currency_code,
        location_id=location.id,
        form=AccountForm.CORRESPONDENT,
        parent_id=parent.id,
        partner_id=partner.id,
        is_system=False,
    )
    db.add(account)
    db.flush()
    return account


def _ensure_bank_account(db, *, account_code, account_name, currency_code, form) -> Account:
    existing = db.execute(select(Account).where(Account.code == account_code)).scalar_one_or_none()
    if existing is not None:
        return existing
    location = accounts_repo.get_location_by_code(db, "CHINA")
    parent = accounts_repo.get_account_by_code(db, "1400")
    account = Account(
        code=account_code,
        name_ar=account_name,
        type=AccountType.ASSET,
        currency_code=currency_code,
        location_id=location.id,
        form=form,
        parent_id=parent.id,
        is_system=False,
    )
    db.add(account)
    db.flush()
    return account


def _ensure_client(db) -> Client:
    client = db.execute(select(Client).where(Client.code == "DEMO-C0001")).scalar_one_or_none()
    if client is not None:
        return client
    client = Client(
        code="DEMO-C0001",
        name_ar="أحمد (عميل تجريبي للعرض)",
        search_name="احمد (عميل تجريبي للعرض)",
        credit_allowed=False,
    )
    db.add(client)
    db.flush()
    return client


def print_entry(db, entry, title: str) -> None:
    print(f"\n=== {title} — {entry.entry_no} ({entry.operation_type.value}) — {entry.status.value} ===")
    lines = db.execute(
        select(JournalLine).where(JournalLine.entry_id == entry.id).order_by(JournalLine.line_no)
    ).scalars().all()
    for line in lines:
        account = db.get(Account, line.account_id)
        side = f"مدين {line.debit}" if line.debit else f"دائن {line.credit}"
        print(f"  [{line.line_no}] {account.code:<8} {account.name_ar:<30} {side} {line.currency_code}")
    if entry.profit_amount is not None:
        label = "ربح" if entry.profit_amount > 0 else ("خسارة" if entry.profit_amount < 0 else "بلا ربح/خسارة")
        print(f"  → {label} العملية: {abs(entry.profit_amount)} {entry.profit_currency}")


def main() -> None:
    db = SessionLocal()
    try:
        now = clock.system_clock()
        user = _ensure_demo_user(db)
        client = _ensure_client(db)

        libya_office = _ensure_partner_account(
            db,
            partner_code="DEMO-P-LY01",
            partner_name="مكتب A (تجريبي)",
            country="LY",
            account_code="1311",
            account_name="مكتب A · طرابلس · LYD",
            currency_code="LYD",
            location_code="TRIPOLI",
            parent_code="1310",
        )
        turkish_company = _ensure_partner_account(
            db,
            partner_code="DEMO-P-TR01",
            partner_name="شركة تركية ١ (تجريبي)",
            country="TR",
            account_code="1321",
            account_name="شركة تركية ١ · USD",
            currency_code="USD",
            location_code="TURKEY",
            parent_code="1320",
        )
        china_cny_bank = _ensure_bank_account(
            db, account_code="1420", account_name="بنك الصين A · CNY", currency_code="CNY", form=AccountForm.BANK
        )
        db.commit()

        # ── تمويل تمهيدي واقعي عبر RECEIPT حقيقية (لا فتح أرصدة مباشر) ─────
        receipt.execute(
            db, client=client, currency_code="USD", location_code="TRIPOLI", amount=Decimal("50000.00"),
            receiving_account_code="1104", work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=_uuid(), description="تمويل تجريبي — 1104",
        )
        receipt.execute(
            db, client=client, currency_code="USD", location_code="TURKEY", amount=Decimal("200000.00"),
            receiving_account_code="1321", work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=_uuid(), description="تمويل تجريبي — 1321",
        )
        receipt.execute(
            db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"),
            receiving_account_code="1311", work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=_uuid(), description="تمويل تجريبي — 1311",
        )
        db.commit()

        # تمويل دفعة رمبي مفتوحة (سعر تكلفة 6.95) عبر سويفت خروج/وصول حقيقيين
        swift_movement_entry = swift_out.execute(
            db, partner_account_code="1321", amount=Decimal("50000.00"), work_timezone=WORK_TZ,
            created_by=user.id, now=now, idempotency_key=_uuid(),
        )
        from app.models import SwiftMovement

        movement = db.execute(
            select(SwiftMovement).where(SwiftMovement.out_entry_id == swift_movement_entry.id)
        ).scalar_one()
        swift_in.execute(
            db, swift_movement_id=movement.id, total_amount=Decimal("50000.00"), fee_amount=Decimal("0.00"),
            receiving_account_code="1420", bank_conversion_rate=Decimal("6.95"), work_timezone=WORK_TZ,
            created_by=user.id, now=now, idempotency_key=_uuid(),
        )
        db.commit()

        # ══════════════════════════ المثال أ ══════════════════════════
        # عمولة فرق التحويل — دولار كاش ليبيا ← تركيا — الربح المتوقع 300 د.ل
        entry_a = cash_transfer.execute(
            db, client=client, currency_code="USD", from_location_code="TRIPOLI", to_location_code="TURKEY",
            amount=Decimal("10000.00"), source_account_code="1104", execution_account_code="1321",
            collection_account_code="1101", commission_currency="LYD",
            client_commission_amount=Decimal("800.000"), cost_commission_amount=Decimal("500.000"),
            cost_correspondent_account_code="1311", work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=_uuid(),
        )
        db.commit()
        print_entry(db, entry_a, "المثال أ — عمولة فرق التحويل")

        # ══════════════════════════ المثال ب ══════════════════════════
        # فرق سعر الصرف — REMIT_OUT عبر شركة تركية — الربح المتوقع 147.06 $
        entry_b = remit_out.execute(
            db, client=client, from_location_code="TURKEY", partner_account_code="1321", currency_code="CNY",
            amount=Decimal("69000.00"), cost_rate=Decimal("6.90"), client_rate=Decimal("6.80"),
            work_timezone=WORK_TZ, created_by=user.id, now=now, idempotency_key=_uuid(),
        )
        db.commit()
        print_entry(db, entry_b, "المثال ب — فرق سعر الصرف (REMIT_OUT)")

        # ══════════════════════════ المثال ج ══════════════════════════
        # بيع رمبي من مخزون السويفت — الربح المتوقع 107.91 $
        entry_c = exchange.execute_via_lot(
            db, client=client, from_location_code="TURKEY", to_location_code="CHINA",
            amount=Decimal("5000.00"), client_rate=Decimal("6.80"), work_timezone=WORK_TZ,
            created_by=user.id, now=now, idempotency_key=_uuid(),
        )
        db.commit()
        print_entry(db, entry_c, "المثال ج — بيع رمبي من مخزون السويفت (EXCHANGE via lot)")

        print("\nتحقق سريع من التوقعات:")
        print(f"  أ) الربح المتوقع 300.000 LYD — الفعلي: {entry_a.profit_amount} {entry_a.profit_currency}")
        print(f"  ب) الربح المتوقع 147.06 USD — الفعلي: {entry_b.profit_amount} {entry_b.profit_currency}")
        print(f"  ج) الربح المتوقع 107.91 USD — الفعلي: {entry_c.profit_amount} {entry_c.profit_currency}")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
