"""عمولة الصرافة الاختيارية في المتصفح (٢٠٢٦-١٠-٠٤): قسم مطويّ، عملة مستقلة عن عملتي الصرف، حساب مفلتر بعملة العمولة،
نطاق العميل بسعرين ونطاق الخزينة بسعر واحد، والقيد الفعلي زوج أسطر متوازن بعملتها."""

from __future__ import annotations

import json
import os
import re
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, text

from app.database import SessionLocal
from app.models import Account, JournalEntry, JournalLine
from tests.ui_support import _composer, _open_tab, journal_page, live_server, qa_identity  # noqa: F401


def _shot(pg, name):
    out = os.environ.get("COMM_SHOTS_DIR")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(Path(out) / name))


def _api(pg, method, path, body=None):
    res = pg.evaluate("""async ([method, path, body, key]) => {
        const csrf = document.cookie.split('; ').find((c) => c.startsWith('wamda_csrf='))?.split('=')[1] ?? '';
        const r = await fetch(path, {method, credentials: 'same-origin', body: body ? JSON.stringify(body) : undefined,
          headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'Idempotency-Key': key}});
        return {status: r.status, text: await r.text()};
    }""", [method, path, body, uuid.uuid4().hex])
    return res


def _pill(comp, label):
    return comp.locator(".commission-body [role=tab]", has_text=label)


def _sel(pg, comp, label_rx):
    return comp.locator(".field", has=pg.locator("label.field-label", has_text=re.compile(label_rx))).locator("select").first


def _pick_account(pg, comp, code):
    acct = comp.locator(".commission-body .acct-picker")
    acct.locator("button.acct-picker-trigger").click()
    rows = acct.locator(".acct-picker-row")
    rows.first.wait_for(timeout=5000)
    texts = rows.all_inner_texts()
    rows.filter(has_text=code).first.click()
    return texts


def test_client_scope_commission_flow_and_actual_entry(journal_page):
    pg = journal_page
    pg.mode = "real"
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    db = SessionLocal()
    try:
        cid = db.execute(text("SELECT id FROM clients WHERE code = :c"), {"c": pg.client_code}).scalar_one()
    finally:
        db.close()
    r = _api(pg, "POST", "/operations/receipt", {"client_id": cid, "currency_code": "USD", "location_code": "TRIPOLI", "amount": "5000.00", "receiving_account_code": "1104"})
    assert r["status"] == 201, r["text"]
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    pg.fill("#client-search", pg.client_code)
    pg.locator(".client-result", has_text=pg.client_code).first.click()
    pg.wait_for_selector(".client-profile")
    _open_tab(pg, "EXCHANGE")
    comp = _composer(pg)

    # القسم مطويّ افتراضياً
    toggle = comp.locator("[data-testid=commission-section] .commission-toggle")
    assert toggle.get_attribute("aria-expanded") == "false" and comp.locator(".commission-body").count() == 0
    _sel(pg, comp, r"^\s*العملة\s*$").select_option("USD")
    _sel(pg, comp, r"^\s*إلى عملة\s*$").select_option("CNY")
    _sel(pg, comp, r"^\s*الموقع\s*$").select_option("TRIPOLI")
    _sel(pg, comp, r"^\s*إلى موقع\s*$").select_option("CHINA")
    comp.locator("#op-amount").fill("1000")
    for label, v in (("سعر العميل", "6.90"), ("سعر التكلفة", "6.95")):
        comp.locator(".field-rate", has=pg.locator("label.field-label", has_text=label)).locator("input").fill(v)

    # فتح القسم: عملة العمولة مستقلة (دينار)، حساب الشركة مفلتر بالدينار فقط
    toggle.click()
    _pill(comp, "نقبضها").click()
    _sel(pg, comp, r"^\s*عملة العمولة\s*$").select_option("LYD")
    comp.locator("#commission-amount").fill("25")
    texts = _pick_account(pg, comp, "1101")
    assert texts and all("دينار" in t for t in texts), texts  # لا حساب دولار ولا يوان
    _shot(pg, "1-client-scope-commission-section.png")
    with pg.expect_response(lambda x: x.request.method == "POST" and x.url.endswith("/operations/exchange")) as info:
        comp.get_by_role("button", name="حفظ وترحيل", exact=True).click()
    assert info.value.status == 201, info.value.text()
    sent = info.value.request.post_data_json
    assert sent["commission_direction"] == "IN" and sent["commission_currency"] == "LYD" and sent["commission_account_code"] == "1101"
    eid = info.value.json()["id"]
    pg.wait_for_timeout(600)

    db = SessionLocal()
    try:
        e = db.get(JournalEntry, eid)
        assert (e.commission_amount, e.commission_currency, e.commission_direction) == (Decimal("25.000000"), "LYD", "IN")
        lines = [(db.get(Account, l.account_id).code, l.currency_code, l.debit, l.credit)
                 for l in db.execute(select(JournalLine).where(JournalLine.entry_id == eid)).scalars()]
        assert ("1101", "LYD", Decimal("25"), Decimal("0")) in lines and ("4111", "LYD", Decimal("0"), Decimal("25")) in lines
    finally:
        db.close()
    # أسطر القيد في السجل بخانات عملتها (٣ للدينار)
    pg.locator(".activity-item").filter(has_text="صرافة").first.click()
    detail = pg.locator(".activity-detail").first
    detail.wait_for()
    amounts = detail.locator("[data-testid=line-amount]").all_inner_texts()
    assert "25.000" in amounts, amounts
    _shot(pg, "2-entry-lines-with-commission.png")


def test_treasury_scope_sends_commission_with_a_single_rate(journal_page):
    pg = journal_page
    pg.mode = "stub"  # نلتقط الطلب فقط؛ لا حسابات خزينة QA تُلوَّث بها قاعدة الاختبار
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    _open_tab(pg, "EXCHANGE")
    comp = _composer(pg)
    comp.locator("button", has_text=re.compile(r"^\s*خزينة\s*$")).first.click()
    pg.wait_for_timeout(300)
    # نطاق الخزينة: سعر واحد وبلا خيار «حساب العميل» للعمولة
    assert comp.locator(".field-rate").count() == 1
    comp.locator("[data-testid=commission-section] .commission-toggle").click()
    assert _pill(comp, "حساب العميل").count() == 0
    _pill(comp, "ندفعها").click()
    _sel(pg, comp, r"^\s*عملة العمولة\s*$").select_option("USD")
    comp.locator("#commission-amount").fill("12")
    acct = comp.locator(".commission-body .acct-picker")
    acct.locator("button.acct-picker-trigger").click()
    rows = acct.locator(".acct-picker-row")
    rows.first.wait_for(timeout=5000)
    assert all("دولار" in t for t in rows.all_inner_texts())
    _shot(pg, "3-treasury-commission-section.png")
