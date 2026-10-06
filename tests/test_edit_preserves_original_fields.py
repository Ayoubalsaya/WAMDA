"""تعديل القيد يحافظ على ما لم يغيّره المستخدم صراحةً (٢٠٢٦-١٠-٠٦، تدقيق U-02).

الجذر: مسارا الإنشاء (`operations.py`) والتعديل (`entry_actions._create_*`) نسختان متوازيتان؛ التعديل أسقط
`entry_date`/`backdate_reason` (فيُؤرَّخ البديل باليوم) ومعهما `collection_location_code` للتحويل النقدي.
هذه الاختبارات: (١) سلوكية على قيد مؤرَّخ بأثر رجعي، (٢) بنيوية تقارن الحقول التي يقرؤها كل مسار تعديل
بما يقرؤه مسار الإنشاء المقابل لكل الأنواع الاثني عشر (فتفشل إن سقط حقل جديد بالطريقة نفسها)."""

from __future__ import annotations

import ast
import inspect
from datetime import date
from decimal import Decimal

import pytest

from sqlalchemy import select

from app.models import ClientCurrencyLocation, JournalEntry, JournalLine, Location
from app.routers import entry_actions, operations
from app.schemas import operations as schemas
from tests import factories as f
from tests.test_edit_prefill_api import _h, _login, client  # noqa: F401

PAST = "2026-03-10"


def _edit(client, eid, operation, reason="تصحيح"):
    return client.post(f"/operations/{eid}/edit", json={"reason": reason, "operation": operation},
                       headers={"X-CSRF-Token": client.cookies.get("wamda_csrf")})


def _make(db, client, url, body):
    r = client.post(url, json={**body, "entry_date": PAST, "backdate_reason": "إدخال متأخر"}, headers=_h(client))
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    orig = db.get(JournalEntry, eid)
    assert orig.entry_date == date.fromisoformat(PAST) and orig.is_backdated and orig.backdate_reason == "إدخال متأخر"
    return eid, orig


def _assert_preserved(db, resp, orig):
    assert resp.status_code == 200, resp.text
    db.expire_all()
    new = db.get(JournalEntry, resp.json()["new_entry"]["id"])
    assert new.entry_date == orig.entry_date, "التعديل أعاد تأريخ القيد"
    assert new.backdate_reason == "إدخال متأخر" and new.is_backdated is True
    return new


def test_edit_keeps_original_date_and_reason_when_the_form_sends_them(db, client, now):
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"), receiving_account_code="1101", user=user, now=now)
    body = {"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "100.000", "receiving_account_code": "1101"}
    eid, orig = _make(db, client, "/operations/receipt", body)
    saved = client.get(f"/operations/{eid}/source-request").json()["request"]
    edited = {k: v for k, v in saved.items() if v is not None} | {"amount": "101.000"}
    _assert_preserved(db, _edit(client, eid, edited), orig)


def test_edit_keeps_original_date_when_the_form_omits_it(db, client, now):
    """قيد قديم بلا طلب محفوظ، أو نموذج لا يرسل التاريخ: يبقى تاريخ الأصل وسببه (لا اليوم)."""
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"), receiving_account_code="1101", user=user, now=now)
    body = {"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "50.000", "paying_account_code": "1101"}
    eid, orig = _make(db, client, "/operations/payment", body)
    stripped = {k: v for k, v in body.items()} | {"amount": "51.000"}
    _assert_preserved(db, _edit(client, eid, stripped), orig)


def test_edit_can_change_the_date_explicitly(db, client, now):
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"), receiving_account_code="1101", user=user, now=now)
    body = {"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "100.000", "receiving_account_code": "1101"}
    eid, _ = _make(db, client, "/operations/receipt", body)
    r = _edit(client, eid, {**body, "entry_date": "2026-04-01", "backdate_reason": "تاريخ صحيح"})
    assert r.status_code == 200, r.text
    new = db.get(JournalEntry, r.json()["new_entry"]["id"])
    assert new.entry_date == date(2026, 4, 1) and new.backdate_reason == "تاريخ صحيح"


def test_edit_keeps_cash_transfer_collection_location(db, client, now):
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(db, client=c, currency_code="USD", location_code="TRIPOLI", amount=Decimal("90000.00"), receiving_account_code="1104", user=user, now=now)
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("50000.000"), receiving_account_code="1101", user=user, now=now)
    cost_corr = f.make_correspondent_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1310")
    exec_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(db, client=f.make_client(db), currency_code="LYD", location_code="TRIPOLI", amount=Decimal("9000.000"), receiving_account_code=cost_corr.code, user=user, now=now)
    f.fund_client(db, client=f.make_client(db), currency_code="USD", location_code="TURKEY", amount=Decimal("90000.00"), receiving_account_code=exec_acct.code, user=user, now=now)
    turkey = db.execute(select(Location).where(Location.code == "TURKEY")).scalar_one()
    db.add(ClientCurrencyLocation(currency_code="LYD", location_id=turkey.id))
    db.flush()
    f.fund_client(db, client=c, currency_code="LYD", location_code="TURKEY", amount=Decimal("5000.000"), receiving_account_code="1101", user=user, now=now)
    body = {"client_id": c.id, "currency_code": "USD", "from_location_code": "TRIPOLI", "to_location_code": "TURKEY", "amount": "10000.00",
            "source_account_code": "1104", "execution_account_code": exec_acct.code, "commission_currency": "LYD", "client_commission_amount": "800.000",
            "cost_commission_amount": "500.000", "cost_correspondent_account_code": cost_corr.code, "collection_location_code": "TURKEY"}
    eid, orig = _make(db, client, "/operations/cash-transfer", body)
    new = _assert_preserved(db, _edit(client, eid, {**body, "amount": "10001.00"}), orig)
    accounts = lambda e: set(db.execute(select(JournalLine.account_id).where(JournalLine.entry_id == e.id)).scalars())  # noqa: E731
    assert accounts(new) == accounts(orig), "حساب تحصيل العمولة (LYD·TURKEY) بقي كما في الأصل"


def _attrs_read(fn: ast.FunctionDef, param: str) -> set[str]:
    read = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == param}
    # `_backdate_kwargs(op)` يقرأ التاريخ وسببه نيابةً عن الدالة
    if any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_backdate_kwargs" for n in ast.walk(fn)):
        read |= {"entry_date", "backdate_reason"}
    return read


def _consumers(module, param_names: tuple[str, ...]) -> dict[str, set[str]]:
    """اسم المخطط ← الحقول التي تقرؤها الدالة التي تستقبله (وسيط payload/op مُعلَّم بالمخطط)."""
    out: dict[str, set[str]] = {}
    tree = ast.parse(inspect.getsource(module))
    for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef)):
        for arg in fn.args.args:
            if arg.arg in param_names and isinstance(arg.annotation, ast.Name) and arg.annotation.id.endswith("Request"):
                out.setdefault(arg.annotation.id, set()).update(_attrs_read(fn, arg.arg))
    return out


_SCHEMAS = ["ReceiptRequest", "PaymentRequest", "ExchangeRatesRequest", "ExchangeLotRequest", "CashTransferRequest", "LocalMoveRequest",
            "RemitOutRequest", "SwiftOutRequest", "SwiftInRequest", "SwiftReturnRequest", "ExpenseRequest", "OpeningRequest", "AdjustmentRequest"]


# حقل في المخطط لا يقرؤه أي مسار لأن المخطط يرفضه بـ٤٢٢ صريح (لا قبول صامت)
_REJECTED = {"LocalMoveRequest": {"commission_location_code"}}


@pytest.mark.parametrize("name", _SCHEMAS)
def test_edit_path_reads_every_field_the_create_path_reads(name):
    created = _consumers(operations, ("payload",))[name]
    edited = _consumers(entry_actions, ("op",))[name]
    # `note` يُحفظ عبر `_remember(entry, request)` (الكائن كله) في المسارين
    fields = set(getattr(schemas, name).model_fields) - {"note"} - _REJECTED.get(name, set())
    assert fields <= created, f"مسار الإنشاء لا يقرأ {sorted(fields - created)}"
    assert fields <= edited, f"مسار التعديل يُسقط الحقول: {sorted(fields - edited)}"


def test_local_move_rejects_a_commission_location_instead_of_ignoring_it(db, client, now):
    _login(db, client)
    r = client.post("/operations/local-move", json={"currency_code": "LYD", "from_account_code": "1101", "to_account_code": "1102", "amount": "5",
                                                      "commission_direction": "OUT", "commission_currency": "LYD", "commission_amount": "1",
                                                      "commission_location_code": "TRIPOLI"}, headers=_h(client))
    assert r.status_code == 422 and "لا موقع للعمولة" in r.text, r.text
