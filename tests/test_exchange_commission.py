"""عمولة اختيارية في الصرافة (٢٠٢٦-١٠-٠٤): زوج أسطر متوازن بعملتها المستقلة عن عملتي الصرف، في نطاقي العميل والخزينة."""

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
from app.models import AccountBalance, JournalEntry, JournalLine
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


def _lines(db, entry_id):
    rows = db.execute(select(JournalLine).where(JournalLine.entry_id == entry_id).order_by(JournalLine.line_no)).scalars().all()
    return [(accounts_repo.get_account_by_id(db, l.account_id).code if hasattr(accounts_repo, "get_account_by_id") else l.account_id,
             l.currency_code, l.debit, l.credit) for l in rows]


def _line_set(db, entry_id):
    from app.models import Account

    out = []
    for l in db.execute(select(JournalLine).where(JournalLine.entry_id == entry_id)).scalars():
        out.append((db.get(Account, l.account_id).code, l.currency_code, l.debit, l.credit))
    return out


def _bal(db, code):
    acc = accounts_repo.get_account_by_code(db, code)
    row = db.get(AccountBalance, acc.id)
    return row.balance if row else Decimal("0")


def _client_with(db, now, user, ccy="USD", amount="5000.00", box="1104"):
    c = f.make_client(db)
    f.fund_client(db, client=c, currency_code=ccy, location_code="TRIPOLI", amount=Decimal(amount), receiving_account_code=box, user=user, now=now)
    return c


def _client_exchange(c, **extra):
    body = {"client_id": c.id, "from_currency": "USD", "from_location_code": "TRIPOLI", "to_currency": "CNY", "to_location_code": "CHINA",
            "amount": "1000", "cost_rate": "6.95", "client_rate": "6.90"}
    body.update(extra)
    return body


def _post(client, body):
    return client.post("/operations/exchange", json=body, headers=_h(client))


def test_client_scope_receive_commission_in_a_third_currency_into_a_company_account(db, client, now):
    """نقبضها بالدينار (لا دولار ولا يوان) في صندوق الدينار: مدين 1101 ← دائن 4111 بعملتها."""
    user = _login(db, client)
    c = _client_with(db, now, user)
    before_cash, before_rev = _bal(db, "1101"), _bal(db, "4111")
    r = _post(client, _client_exchange(c, commission_direction="IN", commission_currency="LYD", commission_amount="25.000", commission_account_code="1101"))
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    lines = _line_set(db, eid)
    assert ("1101", "LYD", Decimal("25.000"), Decimal("0")) in lines and ("4111", "LYD", Decimal("0"), Decimal("25.000")) in lines
    assert len(lines) == 8 or len(lines) >= 6  # أسطر الصرافة + زوج العمولة
    for ccy in {l[1] for l in lines}:  # كل عملة تتوازن داخل نفسها
        assert sum(l[2] for l in lines if l[1] == ccy) == sum(l[3] for l in lines if l[1] == ccy), ccy
    assert _bal(db, "1101") - before_cash == Decimal("25.000") and _bal(db, "4111") - before_rev == Decimal("25.000")
    e = db.get(JournalEntry, eid)
    assert (e.commission_amount, e.commission_currency, e.commission_direction) == (Decimal("25.000"), "LYD", "IN")
    assert recompute.verify(db).commission_problems == []


def test_client_scope_commission_from_the_clients_own_account(db, client, now):
    user = _login(db, client)
    c = _client_with(db, now, user)
    r = _post(client, _client_exchange(c, commission_direction="IN", commission_currency="USD", commission_amount="25", commission_location_code="TRIPOLI"))
    assert r.status_code == 201, r.text
    client_usd = accounts_repo.get_or_create_client_account(db, client=c, currency_code="USD", location_code="TRIPOLI")
    lines = _line_set(db, r.json()["id"])
    assert (client_usd.code, "USD", Decimal("25.00"), Decimal("0")) in lines and ("4112", "USD", Decimal("0"), Decimal("25.00")) in lines


def test_client_scope_pay_commission_from_company_account(db, client, now):
    """ندفعها: مدين 5412 (فرع 5410) ← دائن الحساب المختار."""
    user = _login(db, client)
    c = _client_with(db, now, user)
    r = _post(client, _client_exchange(c, commission_direction="OUT", commission_currency="USD", commission_amount="10", commission_account_code="1104"))
    assert r.status_code == 201, r.text
    lines = _line_set(db, r.json()["id"])
    assert ("5412", "USD", Decimal("10.00"), Decimal("0")) in lines and ("1104", "USD", Decimal("0"), Decimal("10.00")) in lines
    assert db.get(JournalEntry, r.json()["id"]).commission_direction == "OUT"


def _treasury_setup(db, now, user):
    usd = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    cny = f.make_correspondent_account(db, currency_code="CNY", location_code="CHINA", parent_code="1320")
    f.fund_client(db, client=f.make_client(db), currency_code="USD", location_code="TURKEY", amount=Decimal("9000.00"),
                  receiving_account_code=usd.code, user=user, now=now)
    return usd, cny


def test_treasury_scope_both_directions_use_company_accounts_and_single_rate(db, client, now):
    user = _login(db, client)
    usd, cny = _treasury_setup(db, now, user)
    body = {"source_account_code": usd.code, "destination_account_code": cny.code, "from_currency": "USD", "to_currency": "CNY",
            "amount": "1000", "client_rate": "6.9"}
    r_in = _post(client, {**body, "commission_direction": "IN", "commission_currency": "USD", "commission_amount": "20", "commission_account_code": usd.code})
    assert r_in.status_code == 201, r_in.text
    lines = _line_set(db, r_in.json()["id"])
    assert (usd.code, "USD", Decimal("20.00"), Decimal("0")) in lines and ("4112", "USD", Decimal("0"), Decimal("20.00")) in lines
    assert db.get(JournalEntry, r_in.json()["id"]).profit_amount is None  # بسعر واحد: لا ربح، العمولة بند منفصل
    f.fund_client(db, client=f.make_client(db), currency_code="LYD", location_code="TRIPOLI", amount=Decimal("500.000"),
                  receiving_account_code="1101", user=user, now=now)
    r_out = _post(client, {**body, "commission_direction": "OUT", "commission_currency": "LYD", "commission_amount": "15", "commission_account_code": "1101"})
    assert r_out.status_code == 201, r_out.text
    lines = _line_set(db, r_out.json()["id"])
    assert ("5411", "LYD", Decimal("0"), Decimal("0")) not in lines
    assert ("5411", "LYD", Decimal("15.000"), Decimal("0")) in lines and ("1101", "LYD", Decimal("0"), Decimal("15.000")) in lines
    assert recompute.verify(db).commission_problems == []


def test_treasury_requires_a_company_account(db, client, now):
    user = _login(db, client)
    usd, cny = _treasury_setup(db, now, user)
    r = _post(client, {"source_account_code": usd.code, "destination_account_code": cny.code, "from_currency": "USD", "to_currency": "CNY",
                       "amount": "100", "client_rate": "6.9", "commission_direction": "IN", "commission_currency": "USD", "commission_amount": "5"})
    assert r.status_code == 422 and "حساب شركة" in r.json()["detail"], r.text


def test_commission_validation_errors_are_arabic_and_leave_no_entry(db, client, now):
    user = _login(db, client)
    c = _client_with(db, now, user)
    n = db.execute(text("SELECT count(*) FROM journal_entries WHERE status = 'POSTED'")).scalar_one()  # المسودات المرفوضة تُتراجَع مع معاملة الطلب في الإنتاج
    wrong_ccy = _post(client, _client_exchange(c, commission_direction="IN", commission_currency="LYD", commission_amount="5", commission_account_code="1104"))
    assert wrong_ccy.status_code == 422 and "العمولة بعملتها فقط" in wrong_ccy.json()["detail"], wrong_ccy.text
    other = f.make_client(db)
    other_acc = accounts_repo.get_or_create_client_account(db, client=other, currency_code="USD", location_code="TRIPOLI")
    client_acc = _post(client, _client_exchange(c, commission_direction="IN", commission_currency="USD", commission_amount="5", commission_account_code=other_acc.code))
    assert client_acc.status_code == 422 and "ليس حساب شركة" in client_acc.json()["detail"], client_acc.text
    partial = _post(client, _client_exchange(c, commission_direction="IN", commission_amount="5"))
    assert partial.status_code == 422, partial.text
    zero = _post(client, _client_exchange(c, commission_direction="IN", commission_currency="USD", commission_amount="0", commission_account_code="1104"))
    assert zero.status_code == 422, zero.text
    both = _post(client, _client_exchange(c, commission_direction="IN", commission_currency="USD", commission_amount="5",
                                          commission_account_code="1104", commission_location_code="TRIPOLI"))
    assert both.status_code == 422, both.text
    assert db.execute(text("SELECT count(*) FROM journal_entries WHERE status = 'POSTED'")).scalar_one() == n


def test_credit_policy_applies_to_a_commission_taken_from_the_clients_account(db, client, now):
    """الائتمان ينطبق على سطر العمولة كأي سطر: عميل بلا ائتمان لا يُخصم أكثر من رصيده."""
    user = _login(db, client)
    c = _client_with(db, now, user, amount="100.00")
    r = _post(client, _client_exchange(c, amount="10", commission_direction="IN", commission_currency="USD", commission_amount="500", commission_location_code="TRIPOLI"))
    assert r.status_code == 409, r.text


def test_cancel_reverses_commission_lines_and_reports_drop_it(db, client, now):
    user = _login(db, client)
    c = _client_with(db, now, user)
    rev_before = _bal(db, "4112")
    r = _post(client, _client_exchange(c, commission_direction="IN", commission_currency="USD", commission_amount="25", commission_account_code="1104"))
    eid = r.json()["id"]
    assert _bal(db, "4112") - rev_before == Decimal("25.00")
    rows = client.get("/reports/profit-by-period").json()
    assert any(x["exchange_commission"] for x in rows)
    cancel = client.post(f"/operations/{eid}/cancel", json={"reason": "اختبار"}, headers={"X-CSRF-Token": client.cookies.get("wamda_csrf")})
    assert cancel.status_code == 200, cancel.text
    assert _bal(db, "4112") == rev_before
    assert recompute.verify(db).commission_problems == []
    for row in client.get("/reports/profit-by-period").json():
        for ca in row["exchange_commission"]:
            assert not (ca["currency_code"] == "USD" and Decimal(ca["amount"]) == Decimal("25")) or False


def test_edit_replaces_the_commission_with_the_entry(db, client, now):
    user = _login(db, client)
    c = _client_with(db, now, user)
    rev_before = _bal(db, "4112")
    r = _post(client, _client_exchange(c, commission_direction="IN", commission_currency="USD", commission_amount="25", commission_account_code="1104"))
    eid = r.json()["id"]
    edit = client.post(f"/operations/{eid}/edit", json={"reason": "تصحيح", "operation": _client_exchange(
        c, commission_direction="IN", commission_currency="USD", commission_amount="40", commission_account_code="1104")},
        headers={"X-CSRF-Token": client.cookies.get("wamda_csrf")})
    assert edit.status_code == 200, edit.text
    assert _bal(db, "4112") - rev_before == Decimal("40.00"), "العمولة القديمة عُكست والجديدة وحدها قائمة"
    new = db.get(JournalEntry, edit.json()["new_entry"]["id"])
    assert new.commission_amount == Decimal("40.00")
    assert recompute.verify(db).commission_problems == []


def test_reports_dashboard_and_receipt_show_commission_separately_per_currency(db, client, now):
    from app.documents.receipt import build_receipt_context
    from app.config import settings

    user = _login(db, client)
    c = _client_with(db, now, user)
    r1 = _post(client, _client_exchange(c, commission_direction="IN", commission_currency="LYD", commission_amount="25", commission_account_code="1101"))
    r2 = _post(client, _client_exchange(c, commission_direction="OUT", commission_currency="LYD", commission_amount="5", commission_account_code="1101"))
    assert r1.status_code == r2.status_code == 201
    totals = {}
    for row in client.get("/reports/profit-by-period").json():
        for ca in row["exchange_commission"]:
            totals[ca["currency_code"]] = totals.get(ca["currency_code"], Decimal("0")) + Decimal(ca["amount"])
    assert totals["LYD"] >= Decimal("20.000")
    spread = client.get("/dashboard/summary").json()["today_profit"]
    assert "exchange_commission" in spread and any(x["currency_code"] == "LYD" for x in spread["exchange_commission"])
    # الإيصال: سطر العمولة بعملتها وخانات عملتها
    ctx = build_receipt_context(db, entry_id=r1.json()["id"], doc_size="a4", now=now, work_timezone=settings.work_timezone)
    assert ctx["commission"] == {"label": "عمولة نقبضها", "amount": "25.000", "currency": "LYD"}
    ctx2 = build_receipt_context(db, entry_id=r2.json()["id"], doc_size="a4", now=now, work_timezone=settings.work_timezone)
    assert ctx2["commission"]["label"] == "عمولة ندفعها"


def test_recompute_verify_fails_when_commission_columns_and_lines_disagree(db, client, now):
    """الاتساق: أعمدة العمولة (المبلغ · العملة · الاتجاه) = الأسطر الفعلية (4110/5410)؛ أي اختلاف يُكشف."""
    user = _login(db, client)
    c = _client_with(db, now, user)
    r = _post(client, _client_exchange(c, commission_direction="IN", commission_currency="USD", commission_amount="25", commission_account_code="1104"))
    eid = r.json()["id"]
    assert recompute.verify(db).commission_problems == []
    db.execute(text("ALTER TABLE journal_entries DISABLE TRIGGER USER"))  # يُلغى بتراجع معاملة الاختبار
    try:
        for column, value, needle in (
            ("commission_amount", "26", "لا تطابق"),
            ("commission_currency", "'LYD'", "لا تطابق"),
            ("commission_direction", "'OUT'", "لا تطابق"),
        ):
            original = db.execute(text(f"SELECT {column} FROM journal_entries WHERE id = :i"), {"i": eid}).scalar_one()
            db.execute(text(f"UPDATE journal_entries SET {column} = {value} WHERE id = :i"), {"i": eid})
            problems = recompute.verify(db).commission_problems
            assert any(needle in p and str(eid) not in p and db.get(JournalEntry, eid).entry_no in p for p in problems), (column, problems)
            assert not recompute.verify(db).ok
            db.execute(text(f"UPDATE journal_entries SET {column} = :v WHERE id = :i"), {"v": original, "i": eid})
        assert recompute.verify(db).commission_problems == []
        # أسطر عمولة بلا أعمدة (والعكس: أعمدة بلا أسطر)
        db.execute(text("UPDATE journal_entries SET commission_amount = NULL, commission_currency = NULL, commission_direction = NULL WHERE id = :i"), {"i": eid})
        assert any("بلا أعمدة" in p for p in recompute.verify(db).commission_problems)
    finally:
        db.execute(text("ALTER TABLE journal_entries ENABLE TRIGGER USER"))


def test_commission_enters_the_net_per_currency_and_stays_a_visible_item(db, client, now):
    """الإيراد يُضاف والمصروف يُطرح في الصافي لكل عملة، وتبقى «عمولة الصرافة» بنداً مستقلاً (٢٠٢٦-١٠-٠٤)."""
    user = _login(db, client)
    c = _client_with(db, now, user)

    def snapshot():
        profit = client.get("/dashboard/summary").json()["today_profit"]
        take = lambda items: {x["currency_code"]: Decimal(x["amount"]) for x in items}
        period = {}
        for row in client.get("/reports/profit-by-period").json():
            for key in ("net_by_currency", "exchange_commission"):
                for x in row[key]:
                    period[(key, x["currency_code"])] = period.get((key, x["currency_code"]), Decimal("0")) + Decimal(x["amount"])
        return take(profit["net_by_currency"]), take(profit["exchange_commission"]), period

    net0, comm0, period0 = snapshot()
    assert _post(client, _client_exchange(c, commission_direction="IN", commission_currency="LYD", commission_amount="25", commission_account_code="1101")).status_code == 201
    assert _post(client, _client_exchange(c, commission_direction="OUT", commission_currency="LYD", commission_amount="5", commission_account_code="1101")).status_code == 201
    net1, comm1, period1 = snapshot()
    g = lambda d, k: d.get(k, Decimal("0"))
    assert g(comm1, "LYD") - g(comm0, "LYD") == Decimal("20.000"), "بند العمولة: +25 − 5"
    # الصافي لعملة العمولة يتحرك بـ٢٠ بالضبط (لا فرق سعر بالدينار في هذه الصرافة)، وفرق السعر بالعملة الأخرى لا يتأثر بالعمولة
    assert g(net1, "LYD") - g(net0, "LYD") == Decimal("20.000")
    assert g(period1, ("net_by_currency", "LYD")) - g(period0, ("net_by_currency", "LYD")) == Decimal("20.000")
    assert g(period1, ("exchange_commission", "LYD")) - g(period0, ("exchange_commission", "LYD")) == Decimal("20.000")


def _chain_body(c, step1_extra=None, step2_extra=None):
    return {
        "client_id": c.id, "note": "سلسلة بعمولة",
        "step1": {"from_currency": "LYD", "to_currency": "USD", "amount": "1000", "client_rate": "5.0", "cost_rate": "4.95",
                  "from_location_code": "TRIPOLI", "to_location_code": "TRIPOLI", **(step1_extra or {})},
        "step2": {"to_currency": "CNY", "client_rate": "6.9", "cost_rate": "6.95", "to_location_code": "CHINA", **(step2_extra or {})},
    }


def test_wizard_commission_per_step_client_scope(db, client, now):
    """عمولة اختيارية لكل خطوة بالمنطق نفسه: الخطوة ١ نقبضها بالدينار، الخطوة ٢ ندفعها بالدولار — كل قيد بأعمدته وأسطره."""
    from app.config import settings
    from app.documents import reports_doc

    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"), receiving_account_code="1101", user=user, now=now)
    f.fund_client(db, client=f.make_client(db), currency_code="USD", location_code="TRIPOLI", amount=Decimal("500.00"), receiving_account_code="1104", user=user, now=now)
    r = client.post("/operations/exchange-chain", json=_chain_body(
        c,
        {"commission_direction": "IN", "commission_currency": "LYD", "commission_amount": "15", "commission_account_code": "1101"},
        {"commission_direction": "OUT", "commission_currency": "USD", "commission_amount": "4", "commission_account_code": "1104"}), headers=_h(client))
    assert r.status_code == 201, r.text
    s1, s2 = r.json()["step1"]["id"], r.json()["step2"]["id"]
    e1, e2 = db.get(JournalEntry, s1), db.get(JournalEntry, s2)
    assert (e1.commission_direction, e1.commission_currency, e1.commission_amount) == ("IN", "LYD", Decimal("15.000000"))
    assert (e2.commission_direction, e2.commission_currency, e2.commission_amount) == ("OUT", "USD", Decimal("4.000000"))
    l1, l2 = _line_set(db, s1), _line_set(db, s2)
    assert ("1101", "LYD", Decimal("15.000"), Decimal("0")) in l1 and ("4111", "LYD", Decimal("0"), Decimal("15.000")) in l1
    assert ("5412", "USD", Decimal("4.00"), Decimal("0")) in l2 and ("1104", "USD", Decimal("0"), Decimal("4.00")) in l2
    assert recompute.verify(db).commission_problems == []
    # ملخص السلسلة يعرض العمولة
    ctx = reports_doc.build_chain_summary_context(db, chain_ref=e1.chain_ref, doc_size="a4", now=now, work_timezone=settings.work_timezone)
    assert ctx["columns"][-1] == "العمولة"
    assert [row[-1] for row in ctx["rows"]] == ["نقبضها 15.000 LYD", "ندفعها 4.00 USD"]
    assert client.get(f"/documents/chain-summary/{e1.chain_ref}.pdf").status_code == 200
    # إلغاء السلسلة يعكس أسطر العمولة معها
    rev_before = _bal(db, "4111")
    cancel = client.post(f"/operations/{s1}/cancel", json={"reason": "اختبار"}, headers={"X-CSRF-Token": client.cookies.get("wamda_csrf")})
    assert cancel.status_code == 200 and cancel.json()["chain_cascade"] is True, cancel.text
    assert _bal(db, "4111") == rev_before - Decimal("15.000")
    assert recompute.verify(db).commission_problems == []


def test_wizard_commission_per_step_treasury_scope_and_validation(db, client, now):
    user = _login(db, client)
    f.fund_client(db, client=f.make_client(db), currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"), receiving_account_code="1101", user=user, now=now)
    cny = f.make_correspondent_account(db, currency_code="CNY", location_code="CHINA", parent_code="1320")
    body = {"step1": {"from_currency": "LYD", "to_currency": "USD", "amount": "1000", "client_rate": "5.0", "source_account_code": "1101",
                      "destination_account_code": "1104", "commission_direction": "OUT", "commission_currency": "LYD", "commission_amount": "8", "commission_account_code": "1101"},
            "step2": {"to_currency": "CNY", "client_rate": "6.9", "destination_account_code": cny.code,
                      "commission_direction": "IN", "commission_currency": "USD", "commission_amount": "3", "commission_account_code": "1104"}}
    r = client.post("/operations/exchange-chain", json=body, headers=_h(client))
    assert r.status_code == 201, r.text
    e1, e2 = db.get(JournalEntry, r.json()["step1"]["id"]), db.get(JournalEntry, r.json()["step2"]["id"])
    assert e1.commission_direction == "OUT" and e2.commission_direction == "IN" and e1.profit_amount is None
    assert recompute.verify(db).commission_problems == []
    # تحقق: خطوة بعمولة ناقصة، وعمولة خزينة بلا حساب شركة
    bad = {**body, "step2": {**body["step2"], "commission_account_code": None}}
    assert client.post("/operations/exchange-chain", json=bad, headers=_h(client)).status_code == 422
    partial = {**body, "step1": {**body["step1"], "commission_currency": None}}
    assert client.post("/operations/exchange-chain", json=partial, headers=_h(client)).status_code == 422
