"""الصرافة في المتصفح (٢٠٢٦-١٠-٠٤): تفتح بعملتين مختلفتين، و«إلى عملة» لا تعرض عملة المصدر، في نطاقي العميل والخزينة، والخادم
يرفض سعراً يُنتج مبلغاً شبه صفري برسالة عربية تظهر في النموذج."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import text

from app.database import SessionLocal
from tests.ui_support import _composer, _open_tab, journal_page, live_server, qa_identity  # noqa: F401


def _field_select(pg, comp, label_rx):
    return comp.locator(".field", has=pg.locator("label.field-label", has_text=re.compile(label_rx))).locator("select").first


def _values(select):
    return select.locator("option").evaluate_all("els => els.map(e => e.value).filter(v => v)")


def _check_scope(pg, comp, scope_label=None):
    if scope_label:
        comp.locator("button", has_text=re.compile(rf"^\s*{scope_label}\s*$")).first.click()
        pg.wait_for_timeout(300)
    frm, to = _field_select(pg, comp, r"^\s*العملة\s*$"), _field_select(pg, comp, r"^\s*إلى عملة\s*$")
    # تفتح بعملتين مختلفتين، لا USD → USD
    assert frm.input_value() and to.input_value() and frm.input_value() != to.input_value(), (frm.input_value(), to.input_value())
    assert frm.input_value() not in _values(to)
    # من الدولار: «إلى» بلا دولار وبقيمة غير دولار
    frm.select_option("USD")
    assert "USD" not in _values(to) and to.input_value() not in ("", "USD")
    # من عملة غير الدولار: «إلى» الدولار وحده
    frm.select_option("CNY")
    assert _values(to) == ["USD"] and to.input_value() == "USD"
    # بعد العودة إلى الدولار لا يبقى «إلى» دولاراً
    frm.select_option("USD")
    assert to.input_value() != "USD"


def test_exchange_screen_never_offers_a_currency_against_itself_both_scopes(journal_page):
    pg = journal_page
    pg.mode = "stub"
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    _open_tab(pg, "EXCHANGE")
    comp = _composer(pg)
    _check_scope(pg, comp)  # نطاق العميل (الافتراضي)
    _check_scope(pg, comp, "خزينة")


def test_server_rejects_a_near_zero_result_and_the_message_is_shown(journal_page):
    pg = journal_page
    pg.mode = "real"
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    db = SessionLocal()
    try:
        cid = db.execute(text("SELECT id FROM clients WHERE code = :c"), {"c": pg.client_code}).scalar_one()
    finally:
        db.close()
    r = pg.evaluate("""async ([body, key]) => {
        const csrf = document.cookie.split('; ').find((c) => c.startsWith('wamda_csrf='))?.split('=')[1] ?? '';
        const x = await fetch('/operations/receipt', {method: 'POST', credentials: 'same-origin', body: JSON.stringify(body),
          headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'Idempotency-Key': key}});
        return x.status;
    }""", [{"client_id": cid, "currency_code": "USD", "location_code": "TRIPOLI", "amount": "5000.00", "receiving_account_code": "1104"}, uuid.uuid4().hex])
    assert r == 201
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    pg.fill("#client-search", pg.client_code)
    pg.locator(".client-result", has_text=pg.client_code).first.click()
    pg.wait_for_selector(".client-profile")
    _open_tab(pg, "EXCHANGE")
    comp = _composer(pg)
    _field_select(pg, comp, r"^\s*العملة\s*$").select_option("USD")
    _field_select(pg, comp, r"^\s*إلى عملة\s*$").select_option("CNY")
    _field_select(pg, comp, r"^\s*الموقع\s*$").select_option("TRIPOLI")
    _field_select(pg, comp, r"^\s*إلى موقع\s*$").select_option("CHINA")
    comp.locator("#op-amount").fill("1595")
    for label in ("سعر العميل", "سعر التكلفة"):
        comp.locator(".field-rate", has=pg.locator("label.field-label", has_text=label)).locator("input").fill("0.00001")
    with pg.expect_response(lambda x: x.request.method == "POST" and x.url.endswith("/operations/exchange")) as info:
        comp.get_by_role("button", name="حفظ وترحيل", exact=True).click()
    assert info.value.status == 422
    pg.wait_for_timeout(500)
    assert "يقارب الصفر" in comp.inner_text()
