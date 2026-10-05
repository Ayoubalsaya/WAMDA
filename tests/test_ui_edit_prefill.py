"""التعديل يفتح مملوءاً بقيم القيد الأصلي في كل أنواع العمليات (٢٠٢٦-١٠-٠٤).

الاختبار يُسقط **طلب الإنشاء الأصلي** (كما يحفظه الخادم على القيد) على نموذج التعديل الحقيقي في متصفح حقيقي، ثم يغيّر المبلغ وحده ويُرسل:
جسم التعديل الذي يصل الخادم يجب أن يحمل كل قيمة أصلية كما هي (العملات · المواقع · الحسابات · الأسعار · العمولة · الملاحظة · التاريخ) والمبلغ الجديد وحده مختلف.
(الطلب الأصلي وقائمة السجل وحركات السويفت تُحقَن عبر اعتراض الشبكة كي لا تتلوّث قاعدة الاختبار بقيود دائمة؛ حفظ الخادم للطلب
واستعادته وإعادة الإنشاء بلا فقد لأي حقل مُختبَر لكل الأنواع على الخادم في `test_edit_prefill_api.py`.)"""

from __future__ import annotations

import json
import re
from datetime import date

import pytest
from sqlalchemy import text

from app.database import SessionLocal
from tests.ui_support import journal_page, live_server, qa_identity  # noqa: F401

TODAY = date.today().isoformat()

# (النوع، الطلب الأصلي، مفتاح المبلغ، معرّف حقل المبلغ في الواجهة)
CASES = {
    "RECEIPT": ({"currency_code": "LYD", "location_code": "TRIPOLI", "amount": "100.000", "receiving_account_code": "1101", "note": "ملاحظة قبض أصلية"}, "amount", "op-amount", True),
    "PAYMENT": ({"currency_code": "LYD", "location_code": "TRIPOLI", "amount": "50.000", "paying_account_code": "1101", "note": "ملاحظة صرف أصلية"}, "amount", "op-amount", True),
    "EXCHANGE_CLIENT_COMPANY_COMMISSION": ({
        "operation_type": "EXCHANGE", "from_currency": "USD", "from_location_code": "TRIPOLI", "to_currency": "CNY", "to_location_code": "CHINA",
        "amount": "1000", "cost_rate": "6.95", "client_rate": "6.90", "commission_direction": "IN", "commission_currency": "LYD",
        "commission_amount": "25.000", "commission_account_code": "1101", "note": "صرافة بعمولة"}, "amount", "op-amount", True),
    "EXCHANGE_CLIENT_CLIENT_COMMISSION": ({
        "operation_type": "EXCHANGE", "from_currency": "USD", "from_location_code": "TRIPOLI", "to_currency": "CNY", "to_location_code": "CHINA",
        "amount": "1000", "cost_rate": "6.95", "client_rate": "6.90", "commission_direction": "OUT", "commission_currency": "USD",
        "commission_amount": "5", "commission_location_code": "TRIPOLI", "note": "عمولة من حساب العميل"}, "amount", "op-amount", True),
    "EXCHANGE_TREASURY": ({
        "operation_type": "EXCHANGE", "source_account_code": "1104", "destination_account_code": "1105", "from_currency": "USD", "to_currency": "CNY",
        "amount": "1000", "client_rate": "6.9", "commission_direction": "OUT", "commission_currency": "USD", "commission_amount": "12",
        "commission_account_code": "1104", "note": "خزينة"}, "amount", "op-amount", False),
    "CASH_TRANSFER_COMPANY_COLLECTION": ({
        "currency_code": "USD", "from_location_code": "TRIPOLI", "to_location_code": "TURKEY", "amount": "10000.00", "source_account_code": "1104",
        "execution_account_code": "1321", "collection_account_code": "1101", "commission_currency": "LYD", "client_commission_amount": "800.000",
        "cost_commission_amount": "500.000", "cost_correspondent_account_code": "1311", "note": "تحويل بعمولة"}, "amount", "ct-amount", True),
    "CASH_TRANSFER_CLIENT_COLLECTION": ({
        "operation_type": "CASH_TRANSFER", "currency_code": "USD", "from_location_code": "TRIPOLI", "to_location_code": "TURKEY", "amount": "10000.00",
        "source_account_code": "1104", "execution_account_code": "1321", "collection_location_code": "TRIPOLI", "commission_currency": "LYD",
        "client_commission_amount": "800.000", "cost_commission_amount": "500.000", "cost_correspondent_account_code": "1311",
        "note": "تحصيل من رصيد العميل"}, "amount", "ct-amount", True),
    "REMIT_OUT": ({"from_location_code": "CHINA", "sending_account_code": "1403", "currency_code": "CNY", "amount": "500.00", "note": "تاجر شنغهاي 998877"}, "amount", "remit-amount", True),
    "EXPENSE": ({"expense_account_code": "5201", "currency_code": "LYD", "paying_account_code": "1101", "amount": "150.000", "description": "إيجار المكتب", "note": "ملاحظة مصروف"}, "amount", "expense-amount", False),
    "SWIFT_OUT": ({"partner_account_code": "1321", "amount": "10000.00", "external_ref": "REF-778", "description": "سويفت", "note": "ملاحظة سويفت"}, "amount", "swiftout-amount", False),
    "SWIFT_IN": ({"swift_movement_id": 777001, "total_amount": "10000.00", "fee_amount": "25.00", "receiving_account_code": "1403", "bank_conversion_rate": "6.7", "note": "وصول"}, "total_amount", "swiftin-total", False),
    "SWIFT_RETURN": ({"swift_movement_id": 777002, "partner_account_code": "1321", "total_amount": "5000.00", "client_location_code": "TURKEY", "return_fee_amount": "50.00", "note": "مرتجع"}, "total_amount", "swiftreturn-total", True),
    "LOCAL_MOVE": ({"currency_code": "LYD", "from_account_code": "1101", "to_account_code": "1102", "amount": "50.000", "note": "نقل داخلي"}, "amount", "localmove-amount", False),
    "LOCAL_MOVE_COMMISSION_PAID": ({
        "operation_type": "LOCAL_MOVE", "currency_code": "USD", "from_account_code": "1104", "to_account_code": "1321", "amount": "500.00",
        "commission_direction": "OUT", "commission_currency": "USD", "commission_amount": "5.00", "commission_account_code": "1321",
        "note": "تحويل خزينة بعمولة"}, "amount", "localmove-amount", False),
    "LOCAL_MOVE_COMMISSION_RECEIVED": ({
        "operation_type": "LOCAL_MOVE", "currency_code": "USD", "from_account_code": "1104", "to_account_code": "1321", "amount": "500.00",
        "commission_direction": "IN", "commission_currency": "LYD", "commission_amount": "20.000", "commission_account_code": "1101",
        "note": "نقل بعمولة مقبوضة"}, "amount", "localmove-amount", False),
    # قيد محفوظ بطلب فيه حقول لم يعد المخطط يعرفها: الخادم ينزعها ويُسمّيها (`_legacy` هنا = ما نزعه) والنموذج يُنبّه ولا يُرسلها
    "LOCAL_MOVE_LEGACY_FIELDS": ({
        "operation_type": "LOCAL_MOVE", "currency_code": "LYD", "from_account_code": "1101", "to_account_code": "1102", "amount": "50.000", "note": "قيد قديم",
        "_legacy": {"fee_amount": "3.000", "gone_field": "x"}}, "amount", "localmove-amount", False),
    "OPENING": ({"account_code": "1101", "currency_code": "LYD", "amount": "5000.000", "is_debit": True, "as_of_date": "2026-01-01", "source_type": "VERIFIED",
                 "confidence": "HIGH", "source_note": "جرد افتتاحي", "note": "رصيد افتتاحي"}, "amount", "opening-amount", False),
    "ADJUSTMENT": ({"account_code": "1101", "currency_code": "LYD", "amount": "10.000", "is_debit": False, "reason": "تسوية جرد", "note": "تسوية", "allow_negative": True}, "amount", "adjustment-amount", False),
}


@pytest.mark.parametrize("name", list(CASES))
def test_edit_opens_prefilled_and_changing_only_the_amount_keeps_everything(journal_page, qa_identity, name):
    pg = journal_page
    request, amount_key, amount_id, with_client = CASES[name]
    request = dict(request)
    legacy = request.pop("_legacy", {})
    op_type = request.pop("operation_type", None) or ("RECEIPT" if name == "RECEIPT" else name)
    if name.startswith("CASH_TRANSFER"):
        op_type = "CASH_TRANSFER"
    elif name.startswith("LOCAL_MOVE"):
        op_type = "LOCAL_MOVE"
    db = SessionLocal()
    try:
        cid = db.execute(text("SELECT id FROM clients WHERE code = :c"), {"c": pg.client_code}).scalar_one()
    finally:
        db.close()
    if with_client:
        request["client_id"] = cid
    if name != "OPENING":  # الرصيد الافتتاحي له as_of_date الخاص ولا تاريخ مشترك
        request.setdefault("entry_date", TODAY)
    entry_id = 990000 + list(CASES).index(name)
    entry = {
        "id": entry_id, "entry_no": f"WMD-9999-{entry_id}", "entry_date": TODAY, "operation_type": op_type, "status": "POSTED", "description": None,
        "note": request.get("note"), "replaces_entry_id": None, "client_id": cid if with_client else None,
        "client_name_ar": "عميل اختبار التعديل" if with_client else None, "profit_amount": None, "profit_currency": None, "chain_ref": None, "lines": [],
    }
    captured: dict = {}

    def entries_route(route):
        if route.request.method == "GET":
            route.fulfill(status=200, content_type="application/json", body=json.dumps([entry]))
        else:
            route.continue_()

    def source_route(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"operation_type": op_type, "kind": "STANDARD", "request": request, "dropped_fields": sorted(legacy)}))

    def edit_route(route):
        captured["body"] = json.loads(route.request.post_data)
        route.fulfill(status=422, content_type="application/json", body=json.dumps({"detail": "رفض مُصطنَع — اختبار التقاط الجسم"}))

    def pending_route(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps([{
            "id": request.get("swift_movement_id", 0), "amount": request.get("total_amount", "0"), "currency_code": "USD", "transfer_date": TODAY,
            "external_ref": "REF", "partner_name_ar": "مراسل اختبار", "out_entry_no": "WMD-OUT", "partner_account_code": request.get("partner_account_code", "1321")}]))

    pg.mode = "stub"
    pg.route(re.compile(r".*/journal/entries(\?.*)?$"), entries_route)
    pg.route(re.compile(rf".*/operations/{entry_id}/source-request$"), source_route)
    pg.route(re.compile(rf".*/operations/{entry_id}/edit$"), edit_route)
    pg.route(re.compile(r".*/reference/swift-movements/pending$"), pending_route)
    try:
        pg.reload(wait_until="networkidle")
        pg.wait_for_selector(".activity-item", timeout=10000)
        pg.locator(".activity-item").first.click()
        pg.locator(".activity-detail").first.get_by_role("button", name="تعديل", exact=True).click()
        modal = pg.locator(".edit-entry-modal")
        modal.wait_for()
        modal.locator(f"#{amount_id}").wait_for(timeout=10000)
        pg.wait_for_timeout(800)  # أثر التعبئة بعد جلب الطلب الأصلي

        # الحقول ظاهرة مملوءة بالقيم الأصلية (المبلغ + الملاحظة)
        assert modal.locator(f"#{amount_id}").input_value() == str(request[amount_key])
        assert modal.locator("#op-note").input_value() == request["note"]
        assert "لا قيم محفوظة" not in modal.inner_text()
        if legacy:  # تنبيه يسمّي الحقول المنزوعة
            body_text = modal.inner_text()
            assert "حقول لم تعد مستخدمة ولن تُنقل" in body_text and all(k in body_text for k in legacy), body_text
        else:
            assert "حقول لم تعد مستخدمة" not in modal.inner_text()

        # تغيير المبلغ وحده
        new_amount = "777.5"
        modal.locator(f"#{amount_id}").fill(new_amount)
        # الزر معطَّل قبل كتابة السبب وسببه ظاهر بجانبه، ثم يزول بعد الكتابة
        submit_btn = modal.get_by_role("button", name="ترحيل التعديل", exact=True)
        assert submit_btn.is_disabled() and "سبب التعديل" in modal.locator("[data-testid=submit-disabled-reason]").inner_text()
        reason = modal.locator(".field", has=pg.locator("label.field-label", has_text="سبب التعديل")).locator("input, textarea").first
        reason.fill("تصحيح المبلغ فقط")
        assert submit_btn.is_enabled() and modal.locator("[data-testid=submit-disabled-reason]").count() == 0
        modal.get_by_role("button", name="ترحيل التعديل", exact=True).dispatch_event("click")
        pg.wait_for_function("true")
        for _ in range(40):
            if "body" in captured:
                break
            pg.wait_for_timeout(100)
        assert "body" in captured, "لم يصل طلب التعديل"
    finally:
        pg.unroute(re.compile(r".*/journal/entries(\?.*)?$"))
        pg.unroute(re.compile(rf".*/operations/{entry_id}/source-request$"))
        pg.unroute(re.compile(rf".*/operations/{entry_id}/edit$"))
        pg.unroute(re.compile(r".*/reference/swift-movements/pending$"))

    sent = captured["body"]["operation"]
    assert captured["body"]["reason"] == "تصحيح المبلغ فقط"
    changed = {amount_key}
    for key, original in request.items():
        if key in changed:
            assert str(sent[key]) == new_amount, (name, key, sent.get(key))
            continue
        assert key in sent, f"{name}: ضاع الحقل {key}"
        assert sent[key] == original, f"{name}: تغيّر {key}: {original!r} → {sent[key]!r}"
    assert not (set(sent) & set(legacy)), f"{name}: حقول منزوعة أُرسلت: {set(sent) & set(legacy)}"
    extra = {k for k, v in sent.items() if k not in request and v is not None}
    assert not extra, f"{name}: حقول جديدة لم تكن في الأصل: {extra}"
