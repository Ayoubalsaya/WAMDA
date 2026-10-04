"""ائتمان بلا سقف في المتصفح (٢٠٢٦-١٠-٠٣): زر عدسة العميل ← تأكيد يذكر الحد المخصص ← عملية بمبلغ هائل بالسالب تنجح ←
إيقاف مع دين قائم (تحذير لا رفض) ← عملية مدينة تُرفض برسالة عربية ← شاشة العميل: ثلاث حالات لكل عملة ← تقرير العملاء المدينون."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from sqlalchemy import text

from app.database import SessionLocal
from app.models import Client
from tests import factories as f
from tests.ui_support import _composer, _open_tab, journal_page, live_server, qa_identity  # noqa: F401


def _shot(pg, name):
    out = os.environ.get("CREDIT_SHOTS_DIR")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(Path(out) / name))


class _Resp:
    def __init__(self, d):
        self.status, self._d = d["status"], d

    def text(self):
        return self._d["text"]

    def json(self):
        import json

        return json.loads(self._d["text"])


def _api(pg, method, path, body=None):
    """fetch من داخل الصفحة نفسها (كوكيز الجلسة + CSRF كما يفعل التطبيق)."""
    return _Resp(pg.evaluate("""async ([method, path, body, key]) => {
        const csrf = document.cookie.split('; ').find((c) => c.startsWith('wamda_csrf='))?.split('=')[1] ?? '';
        const r = await fetch(path, {method, credentials: 'same-origin', body: body ? JSON.stringify(body) : undefined,
          headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'Idempotency-Key': key}});
        return {status: r.status, text: await r.text()};
    }""", [method, path, body, uuid.uuid4().hex]))


def _client_id(code):
    db = SessionLocal()
    try:
        return db.execute(text("SELECT id FROM clients WHERE code = :c"), {"c": code}).scalar_one()
    finally:
        db.close()


def _fund_box(pg):
    """صندوق طرابلس يحتاج رصيداً كي تُصرَف منه مبالغ كبيرة: قبض ضخم من عميل QA آخر."""
    db = SessionLocal()
    try:
        funder = Client(code=f"QA-FUND-{f.uid()[:6].upper()}", name_ar="مموِّل صندوق QA", search_name="مموِّل صندوق QA")
        db.add(funder)
        db.commit()
        funder_id = funder.id
    finally:
        db.close()
    r = _api(pg, "POST", "/operations/receipt", {
        "client_id": funder_id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "9000000000.000", "receiving_account_code": "1101"})
    assert r.status == 201, r.text()


def _wait_status(pg, status):
    pg.wait_for_selector(f"[data-testid=credit-status-badge][data-status={status}]")


def _reset(pg):
    pg.mode = "real"
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")


def _select(pg):
    pg.fill("#client-search", pg.client_code)
    pg.locator(".client-result", has_text=pg.client_code).first.click()
    pg.wait_for_selector(".client-profile")


def _fill_payment(pg, amount, note):
    _open_tab(pg, "PAYMENT")
    comp = _composer(pg)
    comp.locator("#op-amount").fill(amount)
    comp.locator("#op-note").fill(note)
    comp.locator(".field", has=pg.locator("label.field-label", has_text="العملة")).locator("select").first.select_option("LYD")
    comp.locator(".field", has=pg.locator("label.field-label", has_text=re.compile(r"^\s*الموقع\s*$"))).locator("select").select_option("TRIPOLI")
    acct = comp.locator(".acct-picker")
    acct.locator("button.acct-picker-trigger").click()
    acct.locator(".acct-picker-row").filter(has_text="1101").first.click()
    return comp


def test_one_press_unlimited_credit_flow(journal_page, qa_identity):
    pg = journal_page
    _reset(pg)
    cid = _client_id(pg.client_code)
    _fund_box(pg)
    # حد مخصص لعملة (يجب أن يذكره التأكيد) ← الحالة «جزئي»
    assert _api(pg, "PUT", f"/clients/{cid}/credit-limits/USD", {"mode": "LIMIT", "limit_amount": "10000"}).status == 204
    _reset(pg)
    _select(pg)

    badge = pg.locator("[data-testid=credit-status-badge]")
    assert badge.inner_text() == "جزئي"
    _shot(pg, "1-lens-partial.png")

    # نموذج صرف مفتوح بقيم لا يجوز أن تضيع عند تغيير الائتمان
    comp = _fill_payment(pg, "5000000000", "ملاحظة قبل الائتمان")

    # زر واحد: «السماح بائتمان» ← تأكيد واحد يذكر الحد المخصص قبل استبداله
    pg.get_by_role("button", name="السماح بائتمان").click()
    confirm = pg.locator("[data-testid=credit-confirm]")
    confirm.wait_for()
    assert re.search(r"سيُلغى حد 10,000\.00 USD ويصبح بلا سقف", confirm.inner_text()), confirm.inner_text()
    _shot(pg, "2-confirm-replaces-custom-limit.png")
    confirm.get_by_role("button", name="تأكيد").click()
    _wait_status(pg, "OPEN")
    assert badge.inner_text() == "ائتمان مفتوح"
    # لم يضِع شيء من النموذج المفتوح
    assert comp.locator("#op-amount").input_value().replace(",", "") .startswith("5000000000")
    assert comp.locator("#op-note").input_value() == "ملاحظة قبل الائتمان"
    _shot(pg, "3-open-form-kept.png")

    # عملية بمبلغ كبير جداً تنجح بالسالب
    with pg.expect_response(lambda x: x.request.method == "POST" and x.url.endswith("/operations/payment")) as info:
        comp.get_by_role("button", name="حفظ وترحيل", exact=True).click()
    assert info.value.status == 201, info.value.text()
    bal = _api(pg, "GET", f"/clients/{cid}/balances").json()
    assert any(b["currency_code"] == "LYD" and float(b["balance"]) == -5000000000 for b in bal), bal
    pg.wait_for_timeout(600)
    _shot(pg, "4-huge-negative-posted.png")

    # إيقاف الائتمان: تأكيد واحد + تحذير بالدين القائم (لا رفض)
    pg.get_by_role("button", name="إيقاف الائتمان").click()
    confirm = pg.locator("[data-testid=credit-confirm]")
    confirm.wait_for()
    assert "للعميل دين حالي" in confirm.inner_text() and "ستُرفض" in confirm.inner_text(), confirm.inner_text()
    _shot(pg, "5-stop-warns-about-debt.png")
    confirm.get_by_role("button", name="تأكيد").click()
    _wait_status(pg, "STOPPED")
    assert badge.inner_text() == "متوقف"

    # عملية مدينة تُرفض برسالة عربية
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    _select(pg)
    comp = _fill_payment(pg, "1", "بعد الإيقاف")
    with pg.expect_response(lambda x: x.request.method == "POST" and x.url.endswith("/operations/payment")) as info:
        comp.get_by_role("button", name="حفظ وترحيل", exact=True).click()
    assert info.value.status == 409
    pg.wait_for_timeout(500)
    assert "بلا ائتمان" in comp.inner_text()
    _shot(pg, "6-debit-rejected-in-arabic.png")


def test_per_currency_three_states_in_client_screen_and_debtors_report(journal_page, qa_identity):
    pg = journal_page
    _reset(pg)
    cid = _client_id(pg.client_code)
    _fund_box(pg)
    assert _api(pg, "PUT", f"/clients/{cid}/credit-mode", {"mode": "UNLIMITED"}).status == 200
    assert _api(pg, "POST", "/operations/payment", {
        "client_id": cid, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "123.000", "paying_account_code": "1101"}).status == 201
    assert _api(pg, "PUT", f"/clients/{cid}/credit-mode", {"mode": "NONE"}).status == 200
    pg.click("button[title^='العملاء']")
    pg.wait_for_selector(".clients-screen")
    pg.fill(".clients-screen input", qa_identity["client_code"])
    pg.click(f"tr.clients-row:has-text('{qa_identity['client_code']}')")
    pg.wait_for_selector(".client-detail-header")
    editor = pg.locator("[data-testid=credit-limit-editor]")
    assert editor.locator("label.credit-mode-option").count() == 3
    editor.locator("label.credit-mode-option", has_text="حد بمبلغ").click()
    editor.locator("input[inputmode='decimal']").fill("250")
    editor.get_by_role("button", name="حفظ الحد").click()
    _wait_status(pg, "PARTIAL")  # انتظار فعلي لا مهلة ثابتة (الحمل في المجموعة الكاملة يؤخّر الرد)
    assert pg.locator("[data-testid=credit-status-badge]").inner_text() == "جزئي"
    editor.locator("label.credit-mode-option", has_text="بلا سقف").click()
    editor.get_by_role("button", name="حفظ الحد").click()
    pg.wait_for_timeout(600)
    _shot(pg, "7-client-screen-three-states.png")
    got = _api(pg, "GET", f"/clients/{cid}").json()["credit_limits"]
    assert {x["mode"] for x in got} >= {"UNLIMITED"}

    # تقرير العملاء المدينون (+ تصدير Excel) وإجمالي الديون في لوحة التحكم
    pg.click("button[title^='التقارير']")
    pg.click("button.reports-nav-item:has-text('العملاء المدينون')")
    pg.wait_for_selector("[data-testid=debtors-table]")
    assert pg.get_by_role("link", name="تنزيل Excel").count() == 1
    _shot(pg, "8-debtors-report.png")
    pg.click("button[title^='لوحة التحكم']")
    pg.wait_for_timeout(1500)
    _shot(pg, "9-dashboard-client-debts.png")
    assert pg.locator("[data-testid=kpi-client-debts]").count() >= 1
