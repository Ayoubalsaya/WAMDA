"""الإرسال الخارجي في المتصفح (٢٠٢٦-١٠-٠٤): يوان من عميل في موقع الصين عبر حساب يوان ← قيد من سطرين متوازنين بعملة واحدة ←
لا يُطلب حساب دولار ولا سعر (لا سعر عميل/تكلفة، لا ربح، لا تحذير سعر)."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.database import SessionLocal
from app.models import Account, JournalEntry, JournalLine, Partner
from app.models.enums import AccountForm, AccountType
from tests import factories as f
from tests.ui_support import _composer, _open_tab, journal_page, live_server, qa_identity  # noqa: F401


def _shot(pg, name):
    out = os.environ.get("REMIT_SHOTS_DIR")
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


@pytest.fixture()
def yuan_and_dollar_accounts():
    """حساب مراسل يوان وحساب مراسل دولار (للتحقق أن الدولار لا يظهر)، يُحذفان في النهاية بعد تنظيف قيود QA."""
    db = SessionLocal()
    made = {}
    try:
        china = db.execute(text("SELECT id FROM locations WHERE code = 'CHINA'")).scalar_one()
        parent = db.execute(text("SELECT id FROM accounts WHERE code = '1320'")).scalar_one()
        for ccy in ("CNY", "USD"):
            partner = Partner(code=f"QA-P-{f.uid()[:6].upper()}", name_ar=f"شريك QA {ccy}", country="الصين")
            db.add(partner)
            db.flush()
            acc = Account(code=f"QA-{ccy}-{f.uid()[:6].upper()}", name_ar=f"حساب إرسال QA {ccy}", type=AccountType.ASSET,
                          currency_code=ccy, location_id=china, form=AccountForm.CORRESPONDENT, parent_id=parent, partner_id=partner.id)
            db.add(acc)
            db.flush()
            made[ccy] = (acc.id, acc.code, partner.id)
        db.commit()
    finally:
        db.close()
    yield {k: v[1] for k, v in made.items()}
    db = SessionLocal()
    try:
        from app.cli import purge_demo_data

        purge_demo_data._purge(db)
        db.commit()
        for _ccy, (acc_id, _code, partner_id) in made.items():
            try:
                db.execute(text("DELETE FROM account_balances WHERE account_id = :a"), {"a": acc_id})
                db.execute(text("DELETE FROM accounts WHERE id = :a"), {"a": acc_id})
                db.execute(text("DELETE FROM partners WHERE id = :p"), {"p": partner_id})
                db.commit()
            except Exception:
                db.rollback()
    finally:
        db.close()


def test_remit_out_yuan_from_china_client_two_balanced_lines_no_dollar_no_rate(journal_page, qa_identity, yuan_and_dollar_accounts):
    pg = journal_page
    pg.mode = "real"
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    yuan, dollar = yuan_and_dollar_accounts["CNY"], yuan_and_dollar_accounts["USD"]

    # رصيد يوان للعميل في موقع الصين: قبض في حساب اليوان (حساب الشركة سيُرسَل منه لاحقاً)
    db = SessionLocal()
    try:
        cid = db.execute(text("SELECT id FROM clients WHERE code = :c"), {"c": pg.client_code}).scalar_one()
    finally:
        db.close()
    r = _api(pg, "POST", "/operations/receipt", {
        "client_id": cid, "currency_code": "CNY", "location_code": "CHINA", "amount": "80000.00", "receiving_account_code": yuan})
    assert r["status"] == 201, r["text"]

    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    pg.fill("#client-search", pg.client_code)
    pg.locator(".client-result", has_text=pg.client_code).first.click()
    pg.wait_for_selector(".client-profile")
    _open_tab(pg, "REMIT_OUT")
    comp = _composer(pg)

    # لا حقول سعر ولا ربح ولا تحذير سعر في النموذج
    body = comp.inner_text()
    for forbidden in ("سعر العميل", "سعر التكلفة", "الهامش", "ربح", "خسارة"):
        assert forbidden not in body, f"«{forbidden}» ظاهر في نموذج الإرسال الخارجي"
    assert comp.locator(".field-rate").count() == 0

    comp.locator(".field", has=pg.locator("label.field-label", has_text="عملة الإرسال")).locator("select").select_option("CNY")
    comp.locator(".field", has=pg.locator("label.field-label", has_text="الموقع المخصوم")).locator("select").select_option("CHINA")
    acct = comp.locator(".acct-picker")
    acct.locator("button.acct-picker-trigger").click()
    rows = acct.locator(".acct-picker-row")
    rows.first.wait_for(timeout=5000)
    texts = rows.all_inner_texts()
    assert any(yuan in t for t in texts), texts
    assert not any(dollar in t for t in texts), "حساب دولار ظهر في إرسال يوان"
    _shot(pg, "1-only-yuan-accounts.png")
    rows.filter(has_text=yuan).first.click()
    comp.locator("#remit-amount").fill("69000")
    comp.locator("#op-note").fill("تاجر شنغهاي — حساب 998877")
    _shot(pg, "2-remit-form-no-rates.png")
    with pg.expect_response(lambda x: x.request.method == "POST" and x.url.endswith("/operations/remit-out")) as info:
        comp.get_by_role("button", name="حفظ وترحيل", exact=True).click()
    assert info.value.status == 201, info.value.text()
    sent = info.value.request.post_data_json
    assert "cost_rate" not in sent and "client_rate" not in sent and sent["sending_account_code"] == yuan
    entry_id = info.value.json()["id"]
    pg.wait_for_timeout(600)
    _shot(pg, "3-after-post.png")

    # القيد: سطران متوازنان بعملة واحدة، بلا ربح ولا سعر
    db = SessionLocal()
    try:
        entry = db.get(JournalEntry, entry_id)
        lines = db.execute(select(JournalLine).where(JournalLine.entry_id == entry_id).order_by(JournalLine.line_no)).scalars().all()
        assert len(lines) == 2 and {l.currency_code for l in lines} == {"CNY"}
        assert lines[0].debit == lines[1].credit and lines[0].debit > 0 and lines[0].credit == 0 and lines[1].debit == 0
        assert entry.profit_amount is None and entry.client_rate is None and entry.cost_rate is None
        assert db.get(Account, lines[1].account_id).code == yuan
    finally:
        db.close()
