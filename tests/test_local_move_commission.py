"""«تحويل بعمولة» نطاق خزينة = LOCAL_MOVE بعمولة اختيارية (٢٠٢٦-١٠-٠٥، قرار مالك): مسار خادمي واحد، بلا عميل ولا ربح عميل.

مثال المالك: ٥٠٠ دولار من مكتب منصور (ليبيا) إلى مكتب الواثقون (تركيا) والمراسل يدفع العمولة — مدين المنفِّذ، دائن المصدر، وزوج العمولة بعملته
(5410 عند الدفع). حقل الرسوم القديم `fee_amount` (5200) حُذف وحلّت العمولة محله."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.database import get_db
from app.engine import accounts_repo, recompute
from app.main import app
from app.models import Account, AccountBalance, JournalEntry, JournalLine
from app.security.passwords import hash_password
from tests import factories as f


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
    user.totp_secret = "JBSWY3DPEHPK3PXP"
    db.flush()
    r = client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": pyotp.TOTP(user.totp_secret).now()})
    assert r.status_code == 200, r.text
    return user


def _h(client):
    return {"X-CSRF-Token": client.cookies.get("wamda_csrf"), "Idempotency-Key": uuid.uuid4().hex}


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("wamda_csrf")}


def _line_set(db, entry_id):
    return [(db.get(Account, l.account_id).code, l.currency_code, l.debit, l.credit)
            for l in db.execute(select(JournalLine).where(JournalLine.entry_id == entry_id)).scalars()]


def _bal(db, code):
    row = db.get(AccountBalance, accounts_repo.get_account_by_code(db, code).id)
    return row.balance if row else Decimal("0")


def _offices(db, now, user):
    """مكتب منصور (ليبيا) ومكتب الواثقون (تركيا): حسابا مراسل بالدولار، الأول ممول."""
    mansour = f.make_correspondent_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1320")
    wathiqoon = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(db, client=f.make_client(db), currency_code="USD", location_code="TRIPOLI", amount=Decimal("9000.00"),
                  receiving_account_code=mansour.code, user=user, now=now)
    return mansour, wathiqoon


def _move(mansour, wathiqoon, **extra):
    body = {"currency_code": "USD", "from_account_code": mansour.code, "to_account_code": wathiqoon.code, "amount": "500.00", "note": "تحويل خزينة"}
    body.update(extra)
    return body


def _post(client, body):
    return client.post("/operations/local-move", json=body, headers=_h(client))


def test_treasury_transfer_with_paid_commission_is_the_owners_example(db, client, now):
    user = _login(db, client)
    mansour, wathiqoon = _offices(db, now, user)
    cost_before = _bal(db, "5412")
    r = _post(client, _move(mansour, wathiqoon, commission_direction="OUT", commission_currency="USD", commission_amount="5", commission_account_code=mansour.code))
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    lines = _line_set(db, eid)
    assert (wathiqoon.code, "USD", Decimal("500.00"), Decimal("0")) in lines and (mansour.code, "USD", Decimal("0"), Decimal("500.00")) in lines
    assert ("5412", "USD", Decimal("5.00"), Decimal("0")) in lines and (mansour.code, "USD", Decimal("0"), Decimal("5.00")) in lines
    assert len(lines) == 4
    e = db.get(JournalEntry, eid)
    assert e.client_id is None and e.profit_amount is None and e.cost_rate is None and e.client_rate is None
    assert (e.commission_direction, e.commission_currency, e.commission_amount) == ("OUT", "USD", Decimal("5.00"))
    assert _bal(db, "5412") - cost_before == Decimal("5.00")
    assert _bal(db, wathiqoon.code) == Decimal("500.00")
    assert recompute.verify(db).commission_problems == []


def test_commission_in_another_currency_received_into_a_company_account(db, client, now):
    user = _login(db, client)
    mansour, wathiqoon = _offices(db, now, user)
    rev_before = _bal(db, "4111")
    r = _post(client, _move(mansour, wathiqoon, commission_direction="IN", commission_currency="LYD", commission_amount="20.000", commission_account_code="1101"))
    assert r.status_code == 201, r.text
    lines = _line_set(db, r.json()["id"])
    assert ("1101", "LYD", Decimal("20.000"), Decimal("0")) in lines and ("4111", "LYD", Decimal("0"), Decimal("20.000")) in lines
    for ccy in {l[1] for l in lines}:  # كل عملة تتوازن داخل نفسها
        assert sum(l[2] for l in lines if l[1] == ccy) == sum(l[3] for l in lines if l[1] == ccy), ccy
    assert _bal(db, "4111") - rev_before == Decimal("20.000")
    assert recompute.verify(db).commission_problems == []


def test_without_commission_the_entry_is_two_plain_lines(db, client, now):
    user = _login(db, client)
    mansour, wathiqoon = _offices(db, now, user)
    r = _post(client, _move(mansour, wathiqoon))
    assert r.status_code == 201, r.text
    lines = _line_set(db, r.json()["id"])
    assert len(lines) == 2
    e = db.get(JournalEntry, r.json()["id"])
    assert e.commission_amount is None and e.commission_currency is None and e.commission_direction is None


def test_the_old_fee_field_is_rejected_loudly_and_posts_nothing(db, client, now):
    """`fee_amount` أُلغي: إرساله يُرفض بـ٤٢٢ ورسالة عربية صريحة (لا تجاهل صامت) ولا يُرحَّل شيء — حتى بقيمة صفر."""
    user = _login(db, client)
    mansour, wathiqoon = _offices(db, now, user)
    n = db.execute(text("SELECT count(*) FROM journal_entries WHERE status = 'POSTED'")).scalar_one()
    for value in ("7.00", "0"):
        r = _post(client, _move(mansour, wathiqoon, fee_amount=value))
        assert r.status_code == 422, r.text
        assert "حقل الرسوم أُلغي — استخدم قسم العمولة" in r.text, r.text
    assert db.execute(text("SELECT count(*) FROM journal_entries WHERE status = 'POSTED'")).scalar_one() == n


def test_commission_validation_is_arabic_and_posts_nothing(db, client, now):
    user = _login(db, client)
    mansour, wathiqoon = _offices(db, now, user)
    n = db.execute(text("SELECT count(*) FROM journal_entries WHERE status = 'POSTED'")).scalar_one()
    base = dict(commission_direction="OUT", commission_currency="USD", commission_amount="5")
    no_account = _post(client, _move(mansour, wathiqoon, **base))
    assert no_account.status_code == 422 and "حساب شركة" in str(no_account.json()), no_account.text
    wrong_ccy = _post(client, _move(mansour, wathiqoon, **{**base, "commission_currency": "LYD"}, commission_account_code=mansour.code))
    assert wrong_ccy.status_code == 422 and "العمولة بعملتها فقط" in wrong_ccy.json()["detail"], wrong_ccy.text
    other = f.make_client(db)
    client_acc = accounts_repo.get_or_create_client_account(db, client=other, currency_code="USD", location_code="TRIPOLI")
    not_company = _post(client, _move(mansour, wathiqoon, **base, commission_account_code=client_acc.code))
    assert not_company.status_code == 422 and "ليس حساب شركة" in not_company.json()["detail"], not_company.text
    partial = _post(client, _move(mansour, wathiqoon, commission_direction="OUT", commission_amount="5", commission_account_code=mansour.code))
    assert partial.status_code == 422, partial.text
    zero = _post(client, _move(mansour, wathiqoon, **{**base, "commission_amount": "0"}, commission_account_code=mansour.code))
    assert zero.status_code == 422, zero.text
    assert db.execute(text("SELECT count(*) FROM journal_entries WHERE status = 'POSTED'")).scalar_one() == n


def test_negative_balance_guard_applies_to_the_commission_line_too(db, client, now):
    user = _login(db, client)
    mansour, wathiqoon = _offices(db, now, user)
    r = _post(client, _move(mansour, wathiqoon, amount="8999.00", commission_direction="OUT", commission_currency="USD",
                            commission_amount="500", commission_account_code=mansour.code))
    assert r.status_code == 409, r.text


def test_cancel_reverses_the_commission_pair_with_the_transfer(db, client, now):
    user = _login(db, client)
    mansour, wathiqoon = _offices(db, now, user)
    cost_before, src_before = _bal(db, "5412"), _bal(db, mansour.code)
    r = _post(client, _move(mansour, wathiqoon, commission_direction="OUT", commission_currency="USD", commission_amount="5", commission_account_code=mansour.code))
    eid = r.json()["id"]
    assert _bal(db, "5412") - cost_before == Decimal("5.00")
    cancel = client.post(f"/operations/{eid}/cancel", json={"reason": "اختبار"}, headers=_csrf(client))
    assert cancel.status_code == 200, cancel.text
    assert _bal(db, "5412") == cost_before and _bal(db, mansour.code) == src_before and _bal(db, wathiqoon.code) == Decimal("0")
    assert recompute.verify(db).commission_problems == []


def test_edit_replaces_the_commission_and_opens_with_the_original_request(db, client, now):
    user = _login(db, client)
    mansour, wathiqoon = _offices(db, now, user)
    original = _move(mansour, wathiqoon, commission_direction="OUT", commission_currency="USD", commission_amount="5", commission_account_code=mansour.code)
    eid = _post(client, original).json()["id"]
    saved = client.get(f"/operations/{eid}/source-request").json()
    assert saved["operation_type"] == "LOCAL_MOVE" and saved["request"]["commission_amount"] == "5.00" or Decimal(saved["request"]["commission_amount"]) == Decimal("5")
    assert saved["request"]["commission_direction"] == "OUT" and saved["request"]["commission_account_code"] == mansour.code
    cost_before = _bal(db, "5412")
    edit = client.post(f"/operations/{eid}/edit", json={"reason": "تصحيح العمولة", "operation": {**original, "commission_amount": "8"}}, headers=_csrf(client))
    assert edit.status_code == 200, edit.text
    assert _bal(db, "5412") - cost_before == Decimal("3.00"), "عمولة ٥ عُكست وحلّت ٨ مكانها"
    new = db.get(JournalEntry, edit.json()["new_entry"]["id"])
    assert new.commission_amount == Decimal("8.00") and new.operation_type.value == "LOCAL_MOVE"
    assert recompute.verify(db).commission_problems == []


def test_paid_commission_reduces_the_net_per_currency_in_reports(db, client, now):
    """العمولة المدفوعة مصروف يُطرح من صافي عملتها، وتبقى بنداً ظاهراً (قرار ٢٠٢٦-١٠-٠٤ نفسه يسري هنا)."""
    user = _login(db, client)
    mansour, wathiqoon = _offices(db, now, user)

    def today_commission_usd():
        profit = client.get("/dashboard/summary").json()["today_profit"]
        return sum((Decimal(x["amount"]) for x in profit["exchange_commission"] if x["currency_code"] == "USD"), Decimal("0")), \
            sum((Decimal(x["amount"]) for x in profit["net_by_currency"] if x["currency_code"] == "USD"), Decimal("0"))

    comm0, net0 = today_commission_usd()
    assert _post(client, _move(mansour, wathiqoon, commission_direction="OUT", commission_currency="USD", commission_amount="5", commission_account_code=mansour.code)).status_code == 201
    comm1, net1 = today_commission_usd()
    assert comm1 - comm0 == Decimal("-5.00") and net1 - net0 == Decimal("-5.00")


def test_verify_catches_local_move_commission_columns_that_disagree_with_lines(db, client, now):
    user = _login(db, client)
    mansour, wathiqoon = _offices(db, now, user)
    eid = _post(client, _move(mansour, wathiqoon, commission_direction="OUT", commission_currency="USD", commission_amount="5", commission_account_code=mansour.code)).json()["id"]
    assert recompute.verify(db).commission_problems == []
    db.execute(text("ALTER TABLE journal_entries DISABLE TRIGGER USER"))
    try:
        db.execute(text("UPDATE journal_entries SET commission_amount = 6 WHERE id = :i"), {"i": eid})
        assert any("لا تطابق" in p for p in recompute.verify(db).commission_problems)
        db.execute(text("UPDATE journal_entries SET commission_amount = NULL, commission_currency = NULL, commission_direction = NULL WHERE id = :i"), {"i": eid})
        assert any("بلا أعمدة" in p for p in recompute.verify(db).commission_problems)
    finally:
        db.execute(text("ALTER TABLE journal_entries ENABLE TRIGGER USER"))
