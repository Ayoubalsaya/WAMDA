"""إلغاء · تعديل · تعليقات (المرحلة ١٤ب) — `app/routers/entry_actions.py`.

كل اختبار يمرّ عبر `TestClient(app)` الحقيقي (لا استدعاء دوال المحرّك
مباشرة) — الحارس الحقيقي هنا هو مسار HTTP بصلاحياته وCSRF، لا الدالة
الداخلية وحدها.
"""

from __future__ import annotations

from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.engine.operations import exchange as exchange_op
from app.engine.operations import swift_in as swift_in_op
from app.engine.operations import swift_out as swift_out_op
from app.main import app
from app.models import AuditLog, FoundingPeriod, JournalEntry, Period, SwiftMovement
from app.models.enums import EntryStatus
from app.security.passwords import hash_password
from tests import factories as f

WORK_TZ = "Africa/Tripoli"


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(db, client: TestClient, *, role: str = "ADMIN"):
    user = f.make_user(db, role=role)
    user.password_hash = hash_password("Sup3rSecret!1")
    user.must_change_password = False
    user.totp_secret = pyotp.random_base32()
    db.flush()
    code = pyotp.TOTP(user.totp_secret).now()
    resp = client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": code})
    assert resp.status_code == 200
    return user


def _csrf(client: TestClient) -> dict:
    token = client.cookies.get("wamda_csrf")
    assert token
    return {"X-CSRF-Token": token}


def _account_balance(db, code: str) -> Decimal:
    from sqlalchemy import text
    return db.execute(
        text("SELECT COALESCE(a.balance, 0) FROM account_balances a JOIN accounts acc ON acc.id = a.account_id WHERE acc.code = :c"),
        {"c": code},
    ).scalar()


# ═══ إلغاء ═══

def test_cancel_returns_balance_exactly_to_zero(db, client, now):
    """يفحص رصيد حساب العميل نفسه (فريد لكل اختبار، صفر مضمون بدايةً) —
    لا صندوق ١١٠١ المشترك: هذا حساب حي يراكم أرصدة حقيقية من الجلسات
    اليدوية طوال العمل عليه، فمساواته بقيمة مطلقة هشّة."""
    from app.engine import accounts_repo

    user = _login(db, client)
    c = f.make_client(db, name="عميل إلغاء فريد جداً")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("640.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    client_account = accounts_repo.get_or_create_client_account(db, client=c, currency_code="LYD", location_code="TRIPOLI")
    assert _account_balance(db, client_account.code) == Decimal("640.000000")

    resp = client.post(f"/operations/{entry.id}/cancel", json={"reason": "خطأ إدخال"}, headers=_csrf(client))
    assert resp.status_code == 200
    assert resp.json()["cancelled_entry_ids"] == [entry.id]
    assert resp.json()["chain_cascade"] is False

    assert _account_balance(db, client_account.code) == Decimal("0.000000")
    db.refresh(entry)
    assert entry.status == EntryStatus.REVERSED
    assert entry.reversed_by_entry_id is not None


def test_cancel_requires_nonempty_reason(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل سبب إلغاء فريد")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.post(f"/operations/{entry.id}/cancel", json={"reason": ""}, headers=_csrf(client))
    assert resp.status_code == 422


def test_cancel_forbidden_for_accountant(db, client, now):
    """§٧-١٣: إلغاء = EDIT_POSTED_ENTRY، مدير حصراً — محاسب يُرفَض حتى
    لو كان هو من أدخل العملية أصلاً."""
    admin = f.make_user(db, role="ADMIN")
    c = f.make_client(db, name="عميل صلاحية إلغاء فريد")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=admin, now=now,
    )
    _login(db, client, role="ACCOUNTANT")
    resp = client.post(f"/operations/{entry.id}/cancel", json={"reason": "محاولة محاسب"}, headers=_csrf(client))
    assert resp.status_code == 403


def test_cancel_already_reversed_is_conflict(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل إلغاء مزدوج فريد")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    first = client.post(f"/operations/{entry.id}/cancel", json={"reason": "أول إلغاء"}, headers=_csrf(client))
    assert first.status_code == 200
    second = client.post(f"/operations/{entry.id}/cancel", json={"reason": "إلغاء مكرَّر"}, headers=_csrf(client))
    assert second.status_code == 409


def test_cancel_out_of_lifo_order_rejects_cleanly_not_500(db, client, now):
    """اكتُشف حياً (٢٠٢٦-٠٩-٢٥، تحقُّق معالج صرافة الخزينة): إلغاء قبضٍ
    بعد إنفاق قيمته بدفعة لاحقة يدفع رصيد العميل سالباً — كان
    `CreditLimitExceededError` غير مُعالَج في `_run_reversal` فيصل ٥٠٠
    خام بدل ٤٠٩ واضح مطابق لأي قيد جديد يخالف حد الائتمان."""
    from app.engine.operations import payment as payment_op

    user = _login(db, client)
    c = f.make_client(db, name="عميل ترتيب إلغاء غير LIFO")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("500.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    payment_op.execute(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("500.000"),
        paying_account_code="1101", work_timezone=WORK_TZ, created_by=user.id, now=now,
        idempotency_key=f.uid(),
    )

    resp = client.post(f"/operations/{entry.id}/cancel", json={"reason": "إلغاء بعد إنفاق الرصيد"}, headers=_csrf(client))
    assert resp.status_code == 409
    assert resp.status_code != 500


def test_cancel_cascades_whole_chain(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل إلغاء سلسلة فريد")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    chain_ref = f.uid()
    step1 = exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("1000.000"), cost_rate=Decimal("5.00"), client_rate=Decimal("5.05"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), chain_ref=chain_ref, chain_seq=1, chain_total=2,
    )
    exchange_op.execute_via_rates(
        db, client=c, from_currency="USD", from_location_code="TRIPOLI", to_currency="CNY", to_location_code="CHINA",
        amount=Decimal("100.000"), cost_rate=Decimal("6.95"), client_rate=Decimal("6.90"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), chain_ref=chain_ref, chain_seq=2, chain_total=2,
    )
    resp = client.post(f"/operations/{step1.id}/cancel", json={"reason": "إلغاء خطوة من سلسلة"}, headers=_csrf(client))
    assert resp.status_code == 200
    body = resp.json()
    assert body["chain_cascade"] is True
    assert len(body["cancelled_entry_ids"]) == 2

    remaining = db.execute(
        select(JournalEntry).where(JournalEntry.chain_ref == chain_ref, JournalEntry.status == EntryStatus.POSTED)
    ).scalars().all()
    assert remaining == [], "خطوة من السلسلة بقيت مُرحَّلة بعد إلغاء الأخرى"


def test_cancel_swift_in_rejected_when_lot_consumed(db, client, now):
    user = _login(db, client)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    funder = f.make_client(db)
    f.fund_client(
        db, client=funder, currency_code="USD", location_code="TURKEY", amount=Decimal("50000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    bank = f.make_bank_account(db, currency_code="CNY")
    out = swift_out_op.execute(
        db, partner_account_code=partner_acct.code, amount=Decimal("1000.00"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), external_ref="REF-CANCEL-TEST",
    )
    movement = db.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out.id)).scalar_one()
    in_entry = swift_in_op.execute(
        db, swift_movement_id=movement.id, total_amount=Decimal("1000.00"), fee_amount=Decimal("0.00"),
        receiving_account_code=bank.code, bank_conversion_rate=Decimal("6.80"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    buyer = f.make_client(db)
    f.fund_client(
        db, client=buyer, currency_code="USD", location_code="TRIPOLI", amount=Decimal("5000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    exchange_op.execute_via_lot(
        db, client=buyer, from_location_code="TRIPOLI", to_location_code="CHINA", amount=Decimal("500.00"),
        client_rate=Decimal("6.70"), work_timezone=WORK_TZ, created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    resp = client.post(f"/operations/{in_entry.id}/cancel", json={"reason": "محاولة إلغاء بعد استهلاك"}, headers=_csrf(client))
    assert resp.status_code == 409


def test_cancel_blocked_in_closed_period(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل فترة مقفلة فريد")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("300.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    founding = db.get(FoundingPeriod, 1)
    founding.is_open = False
    db.add(Period(year=now.year, month=now.month, is_closed=True))
    db.flush()

    resp = client.post(f"/operations/{entry.id}/cancel", json={"reason": "محاولة إلغاء بعد إقفال الفترة"}, headers=_csrf(client))
    assert resp.status_code == 409
    assert "مقفلة" in resp.json()["detail"]
    db.refresh(entry)
    assert entry.status == EntryStatus.POSTED, "لا يجوز أن يتغيّر شيء عند الرفض"


# ═══ تعديل ═══

def test_edit_is_atomic_and_reflects_only_new_value(db, client, now):
    from app.engine import accounts_repo

    user = _login(db, client)
    c = f.make_client(db, name="عميل تعديل فريد جداً")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("300.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    client_account = accounts_repo.get_or_create_client_account(db, client=c, currency_code="LYD", location_code="TRIPOLI")
    assert _account_balance(db, client_account.code) == Decimal("300.000000")

    resp = client.post(f"/operations/{entry.id}/edit", json={
        "reason": "تصحيح قيمة",
        "operation": {
            "client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI",
            "amount": "750.000", "receiving_account_code": "1101",
        },
    }, headers=_csrf(client))
    assert resp.status_code == 200
    body = resp.json()
    assert body["reversed_entry_id"] == entry.id
    new_id = body["new_entry"]["id"]

    assert _account_balance(db, client_account.code) == Decimal("750.000000"), "الرصيد لم يعكس القيمة الجديدة فقط"
    db.refresh(entry)
    assert entry.status == EntryStatus.REVERSED
    new_entry = db.get(JournalEntry, new_id)
    assert new_entry.replaces_entry_id == entry.id
    assert new_entry.status == EntryStatus.POSTED


def test_edit_rolls_back_completely_on_invalid_new_value(db, client, now):
    """ذرّية حقيقية: قيمة جديدة تفشل التحقّق (مبلغ سالب) يجب ألا تترك
    القيد الأصلي معكوساً بلا بديل."""
    from app.engine import accounts_repo

    user = _login(db, client)
    c = f.make_client(db, name="عميل تعديل فاشل فريد")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("300.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    client_account = accounts_repo.get_or_create_client_account(db, client=c, currency_code="LYD", location_code="TRIPOLI")
    resp = client.post(f"/operations/{entry.id}/edit", json={
        "reason": "تعديل بقيمة غير صالحة",
        "operation": {
            "client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI",
            "amount": "-50.000", "receiving_account_code": "1101",
        },
    }, headers=_csrf(client))
    assert resp.status_code == 422
    db.refresh(entry)
    assert entry.status == EntryStatus.POSTED, "فشل الإنشاء الجديد يجب ألا يترك الأصل معكوساً"
    assert _account_balance(db, client_account.code) == Decimal("300.000000")


def test_edit_forbidden_for_accountant(db, client, now):
    admin = f.make_user(db, role="ADMIN")
    c = f.make_client(db, name="عميل صلاحية تعديل فريد")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=admin, now=now,
    )
    _login(db, client, role="ACCOUNTANT")
    resp = client.post(f"/operations/{entry.id}/edit", json={
        "reason": "محاولة محاسب",
        "operation": {"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "200", "receiving_account_code": "1101"},
    }, headers=_csrf(client))
    assert resp.status_code == 403


def test_edit_blocked_for_chained_entry(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل تعديل سلسلة فريد")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    chain_ref = f.uid()
    step1 = exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("1000.000"), cost_rate=Decimal("5.00"), client_rate=Decimal("5.05"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), chain_ref=chain_ref, chain_seq=1, chain_total=2,
    )
    exchange_op.execute_via_rates(
        db, client=c, from_currency="USD", from_location_code="TRIPOLI", to_currency="CNY", to_location_code="CHINA",
        amount=Decimal("100.000"), cost_rate=Decimal("6.95"), client_rate=Decimal("6.90"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), chain_ref=chain_ref, chain_seq=2, chain_total=2,
    )
    resp = client.post(f"/operations/{step1.id}/edit", json={
        "reason": "محاولة تعديل خطوة سلسلة",
        "operation": {
            "client_id": c.id, "from_currency": "LYD", "from_location_code": "TRIPOLI", "to_currency": "USD",
            "to_location_code": "TRIPOLI", "amount": "500", "cost_rate": "5.00", "client_rate": "5.05",
        },
    }, headers=_csrf(client))
    assert resp.status_code == 409


# ═══ تعليقات ═══

def test_comment_add_list_and_audit(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل تعليق فريد")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.post(f"/operations/{entry.id}/comments", json={"body": "راجعت هذا القيد مع العميل هاتفياً"}, headers=_csrf(client))
    assert resp.status_code == 201
    assert resp.json()["created_by_name"] == user.full_name

    listed = client.get(f"/operations/{entry.id}/comments")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["body"] == "راجعت هذا القيد مع العميل هاتفياً"

    all_comment_logs = db.execute(select(AuditLog).where(AuditLog.action == "ENTRY_COMMENT_ADDED")).scalars().all()
    audit_rows = [r for r in all_comment_logs if r.after_json and r.after_json.get("entry_id") == entry.id]
    assert len(audit_rows) == 1
    assert audit_rows[0].entity == "entry_comments"


def test_comment_empty_body_rejected(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل تعليق فارغ فريد")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.post(f"/operations/{entry.id}/comments", json={"body": ""}, headers=_csrf(client))
    assert resp.status_code == 422


def test_comment_allowed_for_accountant(db, client, now):
    """التعليقات POST_ENTRY (مدير+محاسب) — بخلاف الإلغاء/التعديل."""
    admin = f.make_user(db, role="ADMIN")
    c = f.make_client(db, name="عميل تعليق محاسب فريد")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=admin, now=now,
    )
    _login(db, client, role="ACCOUNTANT")
    resp = client.post(f"/operations/{entry.id}/comments", json={"body": "تعليق محاسب"}, headers=_csrf(client))
    assert resp.status_code == 201


# ═══ السجل الكامل ═══

def test_history_walks_original_reversal_and_replacement(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل سجل فريد")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("300.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    edit_resp = client.post(f"/operations/{entry.id}/edit", json={
        "reason": "تصحيح للسجل",
        "operation": {"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "500", "receiving_account_code": "1101"},
    }, headers=_csrf(client))
    new_id = edit_resp.json()["new_entry"]["id"]

    hist = client.get(f"/operations/{new_id}/history")
    assert hist.status_code == 200
    kinds = {s["kind"] for s in hist.json()["steps"]}
    assert kinds == {"original", "reversal", "replacement"}
    assert len(hist.json()["steps"]) == 3


def test_edit_treasury_exchange_single_rate(db, client, now):
    """٢٠٢٦-١٠-٠٢: تعديل قيد صرافة خزينة (بلا عميل، سعر واحد) — كان مسار
    التعديل يستدعي `_get_client(None)` فيفشل لكل قيد خزينة."""
    from app.engine.operations import opening_balance
    from app.models.enums import ConfidenceLevel, OpeningSourceType

    admin = _login(db, client)
    lyd = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1100")
    usd = f.make_bank_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1100")
    opening_balance.execute(
        db, account_code=lyd.code, currency_code="LYD", amount=Decimal("10000.000"), is_debit=True,
        as_of_date=now.date(), source_type=OpeningSourceType.KNOWN_BALANCE, confidence=ConfidenceLevel.HIGH,
        approved_by=admin.id, created_by=admin.id, now=now, idempotency_key=f.uid(),
    )
    entry = exchange_op.execute_via_rates(
        db, from_currency="LYD", to_currency="USD", amount=Decimal("10000.000"), client_rate=Decimal("7.86"),
        work_timezone=WORK_TZ, source_account_code=lyd.code, destination_account_code=usd.code,
        created_by=admin.id, now=now, idempotency_key=f.uid(),
    )
    assert _account_balance(db, usd.code) == Decimal("1272.260000")

    resp = client.post(f"/operations/{entry.id}/edit", json={
        "reason": "سعر مُدخَل خطأً",
        "operation": {
            "source_account_code": lyd.code, "destination_account_code": usd.code,
            "from_currency": "LYD", "to_currency": "USD", "amount": "10000.000", "client_rate": "8.00",
        },
    }, headers=_csrf(client))
    assert resp.status_code == 200, resp.text
    assert _account_balance(db, usd.code) == Decimal("1250.000000")
    assert _account_balance(db, lyd.code) == Decimal("0.000000")
