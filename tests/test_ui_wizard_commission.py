"""عمولة اختيارية لكل خطوة في معالج الخطوتين (٢٠٢٦-١٠-٠٤): خطوة ١ نقبضها بالدينار، خطوة ٢ ندفعها بالدولار، ويظهران في القيدين وفي ملخص السلسلة."""

from __future__ import annotations

import os
import re
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, text

from app.database import SessionLocal
from app.models import Account, Client, JournalEntry, JournalLine
from tests import factories as f
from tests.ui_support import journal_page, live_server, qa_identity  # noqa: F401


def _shot(pg, name):
    out = os.environ.get("WIZ_SHOTS_DIR")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(Path(out) / name))


def _api(pg, method, path, body=None):
    return pg.evaluate("""async ([method, path, body, key]) => {
        const csrf = document.cookie.split('; ').find((c) => c.startsWith('wamda_csrf='))?.split('=')[1] ?? '';
        const r = await fetch(path, {method, credentials: 'same-origin', body: body ? JSON.stringify(body) : undefined,
          headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'Idempotency-Key': key}});
        return {status: r.status, text: await r.text()};
    }""", [method, path, body, uuid.uuid4().hex])


def _pill(root, label):
    return root.locator("[role=tab]", has_text=label)


def _sel(root, pg, label_rx):
    return root.locator(".field", has=pg.locator("label.field-label", has_text=re.compile(label_rx))).locator("select").first


def test_wizard_commission_on_both_steps_posts_two_entries_with_their_commissions(journal_page):
    pg = journal_page
    pg.mode = "real"
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    db = SessionLocal()
    try:
        cid = db.execute(text("SELECT id FROM clients WHERE code = :c"), {"c": pg.client_code}).scalar_one()
        funder = Client(code=f"QA-FUND-{f.uid()[:6].upper()}", name_ar="مموِّل صندوق QA", search_name="مموِّل صندوق QA")
        db.add(funder)
        db.commit()
        funder_id = funder.id
    finally:
        db.close()
    for body in (
        {"client_id": cid, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "5000.000", "receiving_account_code": "1101"},
        {"client_id": funder_id, "currency_code": "USD", "location_code": "TRIPOLI", "amount": "500.00", "receiving_account_code": "1104"},
    ):
        assert _api(pg, "POST", "/operations/receipt", body)["status"] == 201
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    pg.fill("#client-search", pg.client_code)
    pg.locator(".client-result", has_text=pg.client_code).first.click()
    pg.wait_for_selector(".client-profile")
    pg.get_by_role("button", name=re.compile("معالج الخطوتين")).first.click()
    wiz = pg.locator(".jr-modal")
    wiz.wait_for()

    # الخطوة ١: دينار ← دولار + عمولة نقبضها بالدينار في صندوق الدينار
    _sel(wiz, pg, r"^\s*من موقع\s*$").select_option("TRIPOLI")
    _sel(wiz, pg, r"^\s*موقع الدولار\s*$").select_option("TRIPOLI")
    wiz.locator("#wizard-amount").fill("1000")
    for label, v in (("سعر العميل", "5.0"), ("سعر التكلفة", "4.95")):
        wiz.locator(".field-rate", has=pg.locator("label.field-label", has_text=label)).locator("input").fill(v)
    c1 = wiz.locator("[data-testid=wizard-commission-1]")
    c1.locator(".commission-toggle").click()
    _pill(c1, "نقبضها").click()
    _sel(c1, pg, r"^\s*عملة العمولة\s*$").select_option("LYD")
    c1.locator("#wizard-commission1-amount").fill("15")
    acct = c1.locator(".acct-picker")
    acct.locator("button.acct-picker-trigger").click()
    acct.locator(".acct-picker-row").first.wait_for(timeout=5000)
    acct.locator(".acct-picker-row").filter(has_text="1101").first.click()
    _shot(pg, "1-wizard-step1-commission.png")
    wiz.get_by_role("button", name="التالي", exact=True).click()

    # الخطوة ٢: دولار ← يوان + عمولة ندفعها بالدولار من صندوق الدولار
    _sel(wiz, pg, r"^\s*إلى موقع\s*$").select_option("CHINA")
    for label, v in (("سعر العميل", "6.9"), ("سعر التكلفة", "6.95")):
        wiz.locator(".field-rate", has=pg.locator("label.field-label", has_text=label)).locator("input").fill(v)
    c2 = wiz.locator("[data-testid=wizard-commission-2]")
    c2.locator(".commission-toggle").click()
    _pill(c2, "ندفعها").click()
    _sel(c2, pg, r"^\s*عملة العمولة\s*$").select_option("USD")
    c2.locator("#wizard-commission2-amount").fill("4")
    acct2 = c2.locator(".acct-picker")
    acct2.locator("button.acct-picker-trigger").click()
    acct2.locator(".acct-picker-row").first.wait_for(timeout=5000)
    acct2.locator(".acct-picker-row").filter(has_text="1104").first.click()
    _shot(pg, "2-wizard-step2-commission.png")
    with pg.expect_response(lambda x: x.request.method == "POST" and x.url.endswith("/operations/exchange-chain")) as info:
        wiz.get_by_role("button", name="حفظ السلسلة", exact=True).click()
    assert info.value.status == 201, info.value.text()
    sent = info.value.request.post_data_json
    assert sent["step1"]["commission_direction"] == "IN" and sent["step1"]["commission_account_code"] == "1101"
    assert sent["step2"]["commission_direction"] == "OUT" and sent["step2"]["commission_currency"] == "USD"
    body = info.value.json()

    db = SessionLocal()
    try:
        e1, e2 = db.get(JournalEntry, body["step1"]["id"]), db.get(JournalEntry, body["step2"]["id"])
        assert (e1.commission_direction, e1.commission_currency, e1.commission_amount) == ("IN", "LYD", Decimal("15"))
        assert (e2.commission_direction, e2.commission_currency, e2.commission_amount) == ("OUT", "USD", Decimal("4"))

        def lines(eid):
            return [(db.get(Account, l.account_id).code, l.currency_code, l.debit, l.credit)
                    for l in db.execute(select(JournalLine).where(JournalLine.entry_id == eid)).scalars()]

        l1, l2 = lines(e1.id), lines(e2.id)
        assert ("1101", "LYD", Decimal("15"), Decimal("0")) in l1 and ("4111", "LYD", Decimal("0"), Decimal("15")) in l1
        assert ("5412", "USD", Decimal("4"), Decimal("0")) in l2 and ("1104", "USD", Decimal("0"), Decimal("4")) in l2
    finally:
        db.close()
    pg.wait_for_timeout(500)
    _shot(pg, "3-wizard-saved.png")
