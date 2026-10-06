"""كشف الحساب: المجموع يطابق أسطره بعد الإلغاء والتعديل (٢٠٢٦-١٠-٠٦، تدقيق U-09).

العيّنة: أ=1000 ثم ب=200 ثم ج=140 ثم إلغاء ب. الرصيد الحقيقي = 1140 (`closing_balance` صحيح). كان آخر صف ظاهر (ج) يعرض
1340 لأن ب (المخفي) محسوب في الرصيد المتحرك بينما عكسه (المخفي أيضاً) يأتي بعده بالترتيب (id أكبر بالتاريخ نفسه)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests import factories as f
from tests.test_edit_prefill_api import _h, _login, client  # noqa: F401


def _receipt(client, c, amount):
    r = client.post("/operations/receipt", json={"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": amount,
                                                  "receiving_account_code": "1101"}, headers=_h(client))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _statement(client, c, **extra):
    r = client.get(f"/clients/{c.id}/statement", params={"currency": "LYD", "location": "TRIPOLI", **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _assert_coherent(body):
    rows = body["rows"]
    opening, closing = Decimal(body["opening_balance"]), Decimal(body["closing_balance"])
    # كل صف يتبع سابقه، وأول صف يتبع الافتتاحي، وآخر صف = الختامي
    prev = opening
    for row in rows:
        prev = prev + Decimal(row["credit"]) - Decimal(row["debit"])
        assert Decimal(row["running_balance"]) == prev, row
    assert prev == closing, f"آخر رصيد متحرك {prev} ≠ الختامي {closing}"


@pytest.mark.parametrize("include_reversed", [False, True])
def test_cancel_in_the_middle_keeps_rows_and_total_consistent(db, client, now, include_reversed):
    _login(db, client)
    c = f.make_client(db)
    _receipt(client, c, "1000.000")
    b = _receipt(client, c, "200.000")
    _receipt(client, c, "140.000")
    assert client.post(f"/operations/{b}/cancel", json={"reason": "خطأ إدخال"}, headers={"X-CSRF-Token": client.cookies.get("wamda_csrf")}).status_code == 200
    body = _statement(client, c, include_reversed=str(include_reversed).lower())
    assert Decimal(body["closing_balance"]) == Decimal("1140"), "الرصيد الحقيقي"
    _assert_coherent(body)
    if not include_reversed:
        assert [Decimal(r["credit"]) for r in body["rows"]] == [Decimal("1000"), Decimal("140")]


def test_edit_in_the_middle_keeps_rows_and_total_consistent(db, client, now):
    _login(db, client)
    c = f.make_client(db)
    _receipt(client, c, "1000.000")
    b = _receipt(client, c, "200.000")
    _receipt(client, c, "140.000")
    saved = client.get(f"/operations/{b}/source-request").json()["request"]
    edited = {k: v for k, v in saved.items() if v is not None} | {"amount": "250.000"}
    r = client.post(f"/operations/{b}/edit", json={"reason": "تصحيح المبلغ", "operation": edited}, headers={"X-CSRF-Token": client.cookies.get("wamda_csrf")})
    assert r.status_code == 200, r.text
    body = _statement(client, c)
    assert Decimal(body["closing_balance"]) == Decimal("1390")
    _assert_coherent(body)


def test_date_window_splitting_a_cancelled_pair_stays_consistent(db, client, now):
    """الأصل قبل `from` وعكسه داخل النافذة: يُعرض العكس (نصفه الآخر في الافتتاحي) فيبقى الختامي = الحقيقي."""
    from datetime import timedelta

    from sqlalchemy import text

    from app.models import JournalEntry

    _login(db, client)
    c = f.make_client(db)
    _receipt(client, c, "500.000")
    b = _receipt(client, c, "300.000")
    assert client.post(f"/operations/{b}/cancel", json={"reason": "خطأ"}, headers={"X-CSRF-Token": client.cookies.get("wamda_csrf")}).status_code == 200
    today = db.get(JournalEntry, b).entry_date
    db.execute(text("ALTER TABLE journal_entries DISABLE TRIGGER USER"))
    try:
        db.execute(text("UPDATE journal_entries SET entry_date = :d WHERE id = :i"), {"d": today - timedelta(days=5), "i": b})
    finally:
        db.execute(text("ALTER TABLE journal_entries ENABLE TRIGGER USER"))
    db.expire_all()
    body = _statement(client, c, **{"from": str(today - timedelta(days=1))})
    assert Decimal(body["opening_balance"]) == Decimal("300")  # الأصل المنقول قبل النافذة
    assert Decimal(body["closing_balance"]) == Decimal("500")
    assert [Decimal(r["credit"]) - Decimal(r["debit"]) for r in body["rows"]] == [Decimal("500"), Decimal("-300")], "العكس ظاهر لأن أصله خارج النافذة"
    _assert_coherent(body)


def test_activity_reports_do_not_count_cancelled_operations(db, client, now):
    """نفس الصنف: تقارير النشاط تعدّ قيد العكس (POSTED) وتستثني أصله (REVERSED) فتبقى العملية الملغاة «نشاطاً»؛ والمراسل يجمع سطر العكس وحده."""
    user = _login(db, client)
    c = f.make_client(db)
    partner = f.make_correspondent_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1310")
    base_ccy = {r["key"]: r["entry_count"] for r in client.get("/reports/activity-by-currency").json()}.get("LYD", 0)
    base_top = {r["client_id"]: r["operation_count"] for r in client.get("/dashboard/summary").json()["top_clients"]}.get(c.id, 0)
    keep = _receipt(client, c, "100.000")
    gone = client.post("/operations/receipt", json={"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "70.000",
                                                    "receiving_account_code": partner.code}, headers=_h(client)).json()["id"]
    assert client.post(f"/operations/{gone}/cancel", json={"reason": "خطأ"}, headers={"X-CSRF-Token": client.cookies.get("wamda_csrf")}).status_code == 200
    ccy = {r["key"]: r["entry_count"] for r in client.get("/reports/activity-by-currency").json()}
    assert ccy["LYD"] - base_ccy == 1, "عملية واحدة فعلية (الملغاة وعكسها خارج النشاط)"
    month = client.get("/reports/activity-by-month").json()
    assert sum(r["entry_count"] for r in month) >= 1
    top = {r["client_id"]: r["operation_count"] for r in client.get("/dashboard/summary").json()["top_clients"]}
    assert top.get(c.id, 0) - base_top == 1
    corr = [r for r in client.get("/reports/correspondent-activity").json() if r["partner_id"] == partner.partner_id]
    assert all(r["entry_count"] == 0 for r in corr), corr
    del keep, user
