"""صرافة الخزينة (إنشاءً وتعديلاً وإلغاءً) لا تمسّ دفعات الرمبي أبداً.

سؤال المالك ٢٠٢٦-١٠-٠٢ بعد أن بدت الدفعة LOT-2026-0108 ناقصة ١٣٦ بلا استهلاك:
هل يمكن لتعديل محرك الصرافة (سعر واحد لنطاق الخزينة) أن يكون السبب؟ لا — `execute_via_rates`
لا يستدعي `lots_fifo` أصلاً (الدفعات حصراً في `execute_via_lot` للعميل). هذا الاختبار يثبت ذلك
على أي مسار خزينة (إنشاء · تعديل = عكس+إنشاء · إلغاء) بدفعة رمبي مفتوحة فعلية.
(السبب الفعلي للحادثة: تسرّب اختبار تزامن إلى دفعة المالك في قاعدة التطوير المشتركة —
فُصلت قاعدة الاختبار، انظر tests/conftest.py وPROGRESS.md.)
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.engine import recompute
from app.engine.operations import exchange as exchange_op
from app.engine.operations import opening_balance, swift_in, swift_out
from app.main import app
from app.models import CurrencyLot, LotConsumption, SwiftMovement
from app.models.enums import ConfidenceLevel, OpeningSourceType
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


def _login(db, client):
    user = f.make_user(db, role="ADMIN")
    user.password_hash = hash_password("Sup3rSecret!1")
    user.must_change_password = False
    user.totp_secret = pyotp.random_base32()
    db.flush()
    code = pyotp.TOTP(user.totp_secret).now()
    assert client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": code}).status_code == 200
    return user


def _csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("wamda_csrf"), "Idempotency-Key": f.uid()}


def _open_cny_lot(db, admin, now):
    partner = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    funder = f.make_client(db)
    f.fund_client(db, client=funder, currency_code="USD", location_code="TURKEY", amount=Decimal("20000"),
                  receiving_account_code=partner.code, user=admin, now=now)
    bank = f.make_bank_account(db, currency_code="CNY")
    out = swift_out.execute(db, partner_account_code=partner.code, amount=Decimal("12584"), work_timezone=WORK_TZ,
                            created_by=admin.id, now=now, idempotency_key=f.uid())
    mv = db.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out.id)).scalar_one()
    swift_in.execute(db, swift_movement_id=mv.id, total_amount=Decimal("12584"), fee_amount=Decimal("150"),
                     receiving_account_code=bank.code, bank_conversion_rate=Decimal("6.695"), work_timezone=WORK_TZ,
                     created_by=admin.id, now=now, idempotency_key=f.uid())
    return db.execute(select(CurrencyLot).where(CurrencyLot.account_id == bank.id)).scalar_one()


def _snapshot(db, lot):
    db.refresh(lot)
    n = len(db.execute(select(LotConsumption).where(LotConsumption.lot_id == lot.id)).scalars().all())
    return lot.original_qty, lot.remaining_qty, lot.status, n


def test_treasury_create_edit_cancel_leave_open_lots_untouched(db, client, now):
    admin = _login(db, client)
    lot = _open_cny_lot(db, admin, now)
    before = _snapshot(db, lot)
    assert before[1] == before[0] and before[3] == 0  # دفعة مفتوحة لم يُستهلك منها شيء

    lyd = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1100")
    usd = f.make_bank_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1100")
    cny = f.make_bank_account(db, currency_code="CNY", location_code="CHINA", parent_code="1100")
    opening_balance.execute(
        db, account_code=lyd.code, currency_code="LYD", amount=Decimal("50000.000"), is_debit=True, as_of_date=now.date(),
        source_type=OpeningSourceType.KNOWN_BALANCE, confidence=ConfidenceLevel.HIGH, approved_by=admin.id,
        created_by=admin.id, now=now, idempotency_key=f.uid(),
    )

    # إنشاء: LYD→USD ثم USD→CNY (سلسلة الخزينة بخطوتيها تشمل عملة الرمبي)
    resp = client.post("/operations/exchange-chain", headers=_csrf(client), json={
        "step1": {"from_currency": "LYD", "to_currency": "USD", "amount": "10000.000", "client_rate": "7.86",
                  "source_account_code": lyd.code, "destination_account_code": usd.code},
        "step2": {"to_currency": "CNY", "client_rate": "6.70", "destination_account_code": cny.code},
    })
    assert resp.status_code == 201, resp.text
    assert _snapshot(db, lot) == before

    # تعديل (عكس + إنشاء) لقيد خزينة منفرد
    single = exchange_op.execute_via_rates(
        db, from_currency="LYD", to_currency="USD", amount=Decimal("1000.000"), client_rate=Decimal("7.86"),
        work_timezone=WORK_TZ, source_account_code=lyd.code, destination_account_code=usd.code,
        created_by=admin.id, now=now, idempotency_key=f.uid(),
    )
    resp = client.post(f"/operations/{single.id}/edit", headers=_csrf(client), json={
        "reason": "تصحيح سعر",
        "operation": {"source_account_code": lyd.code, "destination_account_code": usd.code, "from_currency": "LYD",
                      "to_currency": "USD", "amount": "1000.000", "client_rate": "8.00"},
    })
    assert resp.status_code == 200, resp.text
    assert _snapshot(db, lot) == before

    # إلغاء
    new_id = resp.json()["new_entry"]["id"]
    resp = client.post(f"/operations/{new_id}/cancel", headers=_csrf(client), json={"reason": "اختبار"})
    assert resp.status_code == 200, resp.text
    assert _snapshot(db, lot) == before
    assert recompute.verify(db).lot_problems == []
