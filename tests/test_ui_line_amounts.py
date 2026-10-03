"""أسطر القيد في «سجل العمليات» وسجل التدقيق (٢٠٢٦-١٠-٠٤): المبلغ المعروض = مبلغ السطر بخانات **عملته** (دينار ٣ · دولار ٢)،
وكل سطر باتجاهه الفعلي (مدين/دائن) — لا «0.000000» لسطر الدائن ولا أحمر للجميع."""

from __future__ import annotations

import os
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, text

from app.database import SessionLocal
from app.models import Account, JournalLine
from tests.ui_support import journal_page, live_server, qa_identity  # noqa: F401


def _shot(pg, name):
    out = os.environ.get("LINES_SHOTS_DIR")
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


def _decimals(code):
    db = SessionLocal()
    try:
        return db.execute(text("SELECT decimals FROM currencies WHERE code = :c"), {"c": code}).scalar_one()
    finally:
        db.close()


def test_entry_detail_lines_show_actual_amount_side_and_currency_decimals(journal_page):
    pg = journal_page
    pg.mode = "real"
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    db = SessionLocal()
    try:
        cid = db.execute(text("SELECT id FROM clients WHERE code = :c"), {"c": pg.client_code}).scalar_one()
    finally:
        db.close()
    posted = {}
    for ccy, box, amount in (("LYD", "1101", "15000.000"), ("USD", "1104", "15000.00")):
        r = _api(pg, "POST", "/operations/receipt", {
            "client_id": cid, "currency_code": ccy, "location_code": "TRIPOLI", "amount": amount, "receiving_account_code": box})
        assert r["status"] == 201, r["text"]
        import json

        posted[ccy] = json.loads(r["text"])["id"]
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".activity-item", timeout=10000)

    for ccy, entry_id in posted.items():
        # الصف المطابق للقيد: نفتح تفاصيله (الترتيب الأحدث أولاً)
        decimals = _decimals(ccy)
        db = SessionLocal()
        try:
            lines = db.execute(select(JournalLine).where(JournalLine.entry_id == entry_id).order_by(JournalLine.line_no)).scalars().all()
            expected = [("debit" if l.debit > 0 else "credit", (l.debit if l.debit > 0 else l.credit).quantize(Decimal(1).scaleb(-decimals)), db.get(Account, l.account_id).name_ar)
                        for l in lines]
        finally:
            db.close()
        assert len(expected) == 2 and {e[0] for e in expected} == {"debit", "credit"}
        pg.locator(".activity-item").filter(has_text="قبض").nth(0 if ccy == "USD" else 1).click()
        detail = pg.locator(".activity-detail").first
        detail.wait_for()
        shown = detail.locator("[data-testid=entry-line]")
        assert shown.count() == 2
        for i, (side, amount, _name) in enumerate(expected):
            row = shown.nth(i)
            assert row.get_attribute("data-side") == side
            assert row.locator("[data-testid=line-amount]").inner_text() == f"{amount:.{decimals}f}", (ccy, side)
            assert row.locator(".line-dir").inner_text() == ("مدين" if side == "debit" else "دائن")
        assert "000000" not in detail.inner_text(), detail.inner_text()  # لا ست منازل خام
        if ccy == "LYD":
            _shot(pg, "1-lyd-receipt-lines.png")
        else:
            _shot(pg, "2-usd-receipt-lines-two-decimals.png")
        pg.locator(".activity-item").filter(has_text="قبض").nth(0 if ccy == "USD" else 1).click()


def test_audit_log_amounts_follow_currency_decimals(journal_page, qa_identity):
    pg = journal_page
    pg.mode = "real"
    pg.reload(wait_until="networkidle")
    db = SessionLocal()
    try:
        cid = db.execute(text("SELECT id FROM clients WHERE code = :c"), {"c": pg.client_code}).scalar_one()
    finally:
        db.close()
    assert _api(pg, "PUT", f"/clients/{cid}/credit-limits/USD", {"mode": "LIMIT", "limit_amount": "10000"})["status"] == 204
    pg.click("button[title^='الإعدادات']")
    pg.click("button.seg-tab:has-text('سجل التدقيق')")
    pg.fill("#al-action", "CLIENT_CREDIT_LIMIT_SET")
    pg.click("button:has-text('بحث')")
    pg.locator("tr.acc-lot-row").first.click()
    pre = pg.locator("td pre").last
    pre.wait_for()
    body = pre.inner_text()
    assert '"limit_amount": "10000.00"' in body and "10000.000000" not in body, body
    _shot(pg, "3-audit-amount-two-decimals.png")
