"""كل كتابة غير دفترية تترك سطراً في `audit_log` بمنفِّذها وقيمتها قبل/بعد (٢٠٢٦-١٠-٠٦، تدقيق U-05)، والقيد الدفتري سجله بنفسه."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from app.models import AuditLog, JournalEntry
from tests import factories as f
from tests.test_edit_prefill_api import _h, _login, client  # noqa: F401


def _count(db, action):
    return db.execute(select(func.count()).select_from(AuditLog).where(AuditLog.action == action)).scalar_one()


def _last(db, action):
    return db.execute(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id.desc()).limit(1)).scalar_one()


def _do(db, client, user, method, url, body, action, status=(200, 201, 204)):
    before = _count(db, action)
    r = client.request(method, url, json=body, headers=_h(client))
    assert r.status_code in status, (url, r.status_code, r.text)
    assert _count(db, action) == before + 1, f"{method} {url} لم يترك سطر {action}"
    row = _last(db, action)
    assert row.actor_id == user.id
    return r, row


def test_settings_partners_and_client_writes_leave_audit_lines(db, client, now):
    user = _login(db, client)
    _, row = _do(db, client, user, "PUT", "/settings/company", {"name_ar": "ومضة الجديدة"}, "COMPANY_PROFILE_UPDATED")
    assert row.after_json["name_ar"] == "ومضة الجديدة" and "has_logo" in row.after_json and "logo_data_url" not in str(row.after_json)
    _, row = _do(db, client, user, "POST", "/settings/currencies", {"code": "QAZ", "name_ar": "تجريبية", "symbol": "Q", "decimals": 2, "sort_order": 90}, "CURRENCY_CREATED")
    assert row.after_json["code"] == "QAZ"
    _, row = _do(db, client, user, "PATCH", "/settings/currencies/QAZ", {"name_ar": "تجريبية٢"}, "CURRENCY_UPDATED")
    assert row.before_json["name_ar"] == "تجريبية" and row.after_json["name_ar"] == "تجريبية٢"
    _do(db, client, user, "POST", "/settings/locations", {"code": "QA-LOC", "name_ar": "موقع", "country": "ليبيا"}, "LOCATION_CREATED")
    _, row = _do(db, client, user, "PATCH", "/settings/locations/QA-LOC", {"country": "تركيا"}, "LOCATION_UPDATED")
    assert (row.before_json["country"], row.after_json["country"]) == ("ليبيا", "تركيا")
    _do(db, client, user, "POST", "/settings/client-currency-locations", {"currency_code": "QAZ", "location_code": "QA-LOC"}, "CLIENT_CURRENCY_LOCATION_ADDED")
    _do(db, client, user, "POST", "/settings/bank-accounts", {"currency_code": "LYD", "location_code": "TRIPOLI"}, "BANK_ACCOUNT_CREATED")

    r, _ = _do(db, client, user, "POST", "/partners", {"code": "QA-P", "name_ar": "شريك", "country": "تركيا"}, "PARTNER_CREATED")
    _do(db, client, user, "POST", f"/partners/{r.json()['id']}/accounts", {"parent_code": "1320", "currency_code": "USD", "location_code": "TURKEY"}, "PARTNER_ACCOUNT_CREATED")

    c = f.make_client(db)
    _, row = _do(db, client, user, "PATCH", f"/clients/{c.id}", {"phone": "0910000000"}, "CLIENT_UPDATED")
    assert row.after_json["phone"] == "0910000000" and row.before_json["phone"] != row.after_json["phone"]


def test_reconciliation_writes_leave_audit_lines(db, client, now):
    user = _login(db, client)
    acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(db, client=f.make_client(db), currency_code="USD", location_code="TURKEY", amount=Decimal("500.00"), receiving_account_code=acct.code, user=user, now=now)
    r, row = _do(db, client, user, "POST", "/reconciliation/statements", {
        "partner_id": acct.partner_id, "period_from": "2026-10-01", "period_to": "2026-10-31",
        "lines": [{"value_date": "2026-10-02", "amount": "11.00"}, {"value_date": "2026-10-03", "amount": "22.00"}, {"value_date": "2026-10-04", "amount": "33.00"}]},
        "PARTNER_STATEMENT_CREATED")
    assert row.after_json["lines"] == 3
    sid, lines = r.json()["id"], r.json()["lines"]
    _do(db, client, user, "POST", f"/reconciliation/statements/{sid}/auto-match", None, "PARTNER_STATEMENT_AUTO_MATCHED")
    entry_id = db.execute(select(JournalEntry.id).limit(1)).scalar_one()
    _, row = _do(db, client, user, "PATCH", f"/reconciliation/statements/{sid}/lines/{lines[0]['id']}/match", {"entry_id": entry_id}, "STATEMENT_LINE_MATCHED")
    assert (row.before_json["status"], row.after_json["status"], row.after_json["matched_entry_id"]) == ("OPEN", "RESOLVED", entry_id)
    _do(db, client, user, "PATCH", f"/reconciliation/statements/{sid}/lines/{lines[1]['id']}/resolve", {}, "STATEMENT_LINE_RESOLVED")
    _, row = _do(db, client, user, "POST", f"/reconciliation/statements/{sid}/lines/{lines[2]['id']}/adjust", {
        "account_code": acct.code, "currency_code": "USD", "amount": "33.00", "is_debit": True, "reason": "فرق كشف"}, "STATEMENT_LINE_ADJUSTED")
    assert row.after_json["matched_entry_id"] is not None


def test_logouts_are_audited_like_logins(db, client, now):
    user = _login(db, client)
    _do(db, client, user, "POST", "/auth/logout", None, "LOGOUT")


def test_ledger_entries_carry_who_when_and_why_without_duplicating_into_audit_log(db, client, now):
    """القيد الدفتري هو سجله: من (created_by/posted_by) ومتى (created_at/posted_at) ولماذا (الوصف · الملاحظة · سبب الأثر الرجعي · سبب التجاوز)."""
    user = _login(db, client)
    c = f.make_client(db, credit_allowed=True)
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("500.000"), receiving_account_code="1101", user=user, now=now)
    audit_before = db.execute(select(func.count()).select_from(AuditLog)).scalar_one()
    r = client.post("/operations/payment", json={
        "client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "900.000", "paying_account_code": "1101",
        "allow_negative": True, "override_reason": "سقف مؤقت بموافقة المالك", "description": "دفعة مورد", "note": "ملاحظة",
        "entry_date": "2026-03-10", "backdate_reason": "إدخال متأخر"}, headers=_h(client))
    assert r.status_code == 201, r.text
    e = db.get(JournalEntry, r.json()["id"])
    assert e.created_by == user.id and e.posted_by == user.id
    assert e.created_at is not None and e.posted_at is not None
    assert (e.description, e.note, e.backdate_reason) == ("دفعة مورد", "ملاحظة", "إدخال متأخر")
    # سبب التجاوز لا يضيع: سطرا التجاوز الوحيدان في audit_log من المحرك (لا تكرار لأي شيء آخر)
    new_rows = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(db.execute(select(func.count()).select_from(AuditLog)).scalar_one() - audit_before)).scalars().all()
    assert {x.action for x in new_rows} <= {"NEGATIVE_BALANCE_OVERRIDE", "CREDIT_LIMIT_OVERRIDE"}, [x.action for x in new_rows]
    assert all("سقف مؤقت" in (str(x.after_json) + str(x.before_json)) for x in new_rows)
