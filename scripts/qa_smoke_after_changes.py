"""اختبار دخان في متصفح حقيقي بعد تعديلات الأمان/الاستعادة (٢٠٢٦-١٠-٠٦):
 ١) تعديل قيد بتاريخ سابق ← التاريخ يبقى (من الواجهة المبنية)
 ٢) كشف حساب بعد إلغاء ← الرصيد الأخير الظاهر = closing_balance
 ٣) حفظ اسم الشركة من الإعدادات ← الشعار يبقى
 ٤) شاشة الدخول والبوابة: لا رابط «نسيت كلمة المرور» ولا مسار /recover
يعمل على النسخة المبنية المخدومة من 8000 (نفس قاعدة بقية سكربتات QA: مدير QA + عميل جديد بكود فريد).
الاستخدام:
    PYTHONPATH=. venv/Scripts/python.exe scripts/qa_smoke_after_changes.py
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pyotp
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Client, User
from app.security.passwords import hash_password

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "scripts"
QA_USER, QA_PASS, QA_SECRET = "qa_jrnl_admin", "QaJrnl!Pass9", "JBSWY3DPEHPK3PXP"
BASE = "http://127.0.0.1:8000"
TINY_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="

JS_CALL = """async ([method, url, body]) => {
  const m = document.cookie.match(/(?:^|; )wamda_csrf=([^;]*)/);
  const h = {'Content-Type': 'application/json'}; if (m) h['X-CSRF-Token'] = decodeURIComponent(m[1]); if (method === 'POST') h['Idempotency-Key'] = crypto.randomUUID();
  const r = await fetch(url, {method, credentials: 'include', headers: h, body: body ? JSON.stringify(body) : undefined});
  let j = null; try { j = await r.json(); } catch (e) {}
  return {status: r.status, json: j};
}"""


def setup() -> str:
    db = SessionLocal()
    try:
        u = db.execute(select(User).where(User.username == QA_USER)).scalar_one_or_none()
        if u is None:
            u = User(username=QA_USER, full_name="QA smoke", role="ADMIN")
            db.add(u)
        u.password_hash = hash_password(QA_PASS)
        u.role, u.is_active, u.must_change_password = "ADMIN", True, False
        u.totp_secret, u.failed_attempts, u.locked_until = QA_SECRET, 0, None
        code = f"QA-SMK-{uuid.uuid4().hex[:6].upper()}"
        db.add(Client(code=code, name_ar="عميل دخان QA", search_name="عميل دخان QA"))
        db.commit()
        return code
    finally:
        db.close()


def login(pg) -> None:
    pg.goto(f"{BASE}/", wait_until="networkidle")
    pg.wait_for_selector("#username")
    pg.fill("#username", QA_USER)
    pg.fill("#password", QA_PASS)
    pg.click("button:has-text('دخول')")
    pg.wait_for_selector("#totp", timeout=10000)
    pg.fill("#totp", pyotp.TOTP(QA_SECRET).now())
    pg.click("button:has-text('تأكيد')")
    pg.wait_for_selector("nav.sidebar")


def call(pg, method, url, body=None):
    return pg.evaluate(JS_CALL, [method, url, body])


def open_client(pg, code: str) -> None:
    pg.click("button[title^='العملاء']")
    pg.wait_for_selector(".clients-screen")
    pg.fill(".clients-screen input", code)
    pg.wait_for_selector(f"tr.clients-row:has-text('{code}')", timeout=8000)
    pg.click(f"tr.clients-row:has-text('{code}')")
    pg.wait_for_selector(".client-detail-header")
    pg.locator("[aria-label='عملة كشف الحساب']").get_by_text("دولار", exact=False).first.click()
    sel = pg.locator("select:has(option[value='TRIPOLI'])")
    if sel.count():
        sel.first.select_option("TRIPOLI")
    pg.wait_for_timeout(500)


def main() -> int:
    from playwright.sync_api import sync_playwright

    code = setup()
    rep: dict = {"client": code}
    past = (date.today() - timedelta(days=3)).isoformat()
    with sync_playwright() as p:
        br = p.chromium.launch()
        try:
            # ── ٤: شاشتا الدخول (بلا جلسة) ──
            anon = br.new_context(locale="ar").new_page()
            anon.goto(f"{BASE}/", wait_until="networkidle")
            anon.wait_for_selector("#username")
            anon.screenshot(path=str(SHOTS / "_smoke_login.png"))
            rep["login_no_forgot_link"] = anon.locator("a:has-text('نسيت')").count() == 0 and "recover" not in anon.content()
            anon.goto(f"{BASE}/portal", wait_until="networkidle")
            anon.wait_for_selector("#portal-code")
            anon.screenshot(path=str(SHOTS / "_smoke_portal.png"))
            rep["portal_no_forgot_link"] = anon.locator("a:has-text('نسيت')").count() == 0 and "recover" not in anon.content()
            rep["portal_contact_admin_note"] = anon.locator("text=تواصل مع المدير").count() == 1
            rep["recover_routes_status"] = [call(anon, "POST", u, {})["status"] for u in ("/auth/recover/start", "/portal/recover/start")]
            rep["recover_routes_gone"] = all(s in (404, 405) for s in rep["recover_routes_status"])

            ctx = br.new_context(viewport={"width": 1440, "height": 900}, locale="ar")
            pg = ctx.new_page()
            login(pg)
            found = call(pg, "GET", f"/clients?q={code}")["json"]
            found = found if isinstance(found, list) else found.get("items", [])
            cid = found[0]["id"]

            # ── ١: قيد بتاريخ سابق ثم تعديله من الواجهة ──
            rcpt = {"client_id": cid, "currency_code": "USD", "location_code": "TRIPOLI", "amount": "100",
                    "receiving_account_code": "1104", "entry_date": past, "backdate_reason": "QA smoke"}
            r = call(pg, "POST", "/operations/receipt", rcpt)
            rep["receipt_post"] = r["status"]
            if r["status"] >= 300:
                rep["receipt_error"] = r["json"]
                print(json.dumps(rep, ensure_ascii=False, indent=2))
                return 1
            r2 = call(pg, "POST", "/operations/receipt", {**rcpt, "amount": "40", "entry_date": None, "backdate_reason": None})
            rep["receipt2_post"] = r2["status"]

            open_client(pg, code)
            pg.wait_for_selector(f"tr:has-text('{past}')", timeout=8000)
            pg.screenshot(path=str(SHOTS / "_smoke_statement_before.png"))
            pg.locator(f"tr:has-text('{past}')").first.locator("button:has-text('تعديل')").click()
            pg.wait_for_selector("#edit-reason", timeout=8000)
            pg.fill("#edit-reason", "smoke: تعديل المبلغ")
            pg.screenshot(path=str(SHOTS / "_smoke_edit_modal.png"))
            amt = pg.locator(".edit-entry-modal input[inputmode='decimal']").first
            amt.fill("120")
            pg.click(".edit-entry-modal button:has-text('ترحيل التعديل')")
            pg.wait_for_selector(".edit-entry-modal", state="detached", timeout=10000)
            pg.wait_for_timeout(600)
            st = call(pg, "GET", f"/clients/{cid}/statement?currency=USD&location=TRIPOLI")["json"]
            dates = [x["entry_date"] for x in st["rows"]]
            amounts = [x["credit"] for x in st["rows"]]
            rep["statement_after_edit"] = list(zip(dates, amounts))
            rep["edit_keeps_past_date"] = past in dates and any(float(a) == 120.0 for d, a in zip(dates, amounts) if d == past)
            pg.screenshot(path=str(SHOTS / "_smoke_statement_after_edit.png"))

            # ── ٢: إلغاء القيد الثاني ثم مطابقة المجموع ──
            pg.locator("tr", has_text="40.00").first.locator("button:has-text('إلغاء')").click()
            pg.fill("#cancel-reason", "smoke cancel")
            pg.click("button:has-text('تأكيد الإلغاء')")
            pg.wait_for_selector("#cancel-reason", state="detached", timeout=8000)
            pg.wait_for_timeout(800)
            st = call(pg, "GET", f"/clients/{cid}/statement?currency=USD&location=TRIPOLI")["json"]
            last_running = st["rows"][-1]["running_balance"] if st["rows"] else st["opening_balance"]
            rep["statement_after_cancel"] = {"closing": st["closing_balance"], "last_row_running": last_running}
            rep["statement_total_matches"] = float(st["closing_balance"]) == float(last_running) == 120.0
            shown = pg.locator("tbody tr td.num").all_inner_texts()
            pg.screenshot(path=str(SHOTS / "_smoke_statement_after_cancel.png"))
            rep["statement_ui_shows_closing"] = any(t.strip().startswith("120") for t in shown)

            # ── ٣: الشعار يبقى بعد حفظ الاسم من الواجهة ──
            before = call(pg, "GET", "/settings/company")["json"]
            call(pg, "PUT", "/settings/company", {"logo_data_url": TINY_PNG})
            pg.click("button[title^='الإعدادات']")
            pg.wait_for_selector("#settings-company-name")
            pg.fill("#settings-company-name", "شركة دخان QA")
            pg.click("button[type=submit]:has-text('حفظ')")
            pg.wait_for_selector("text=تم الحفظ")
            after = call(pg, "GET", "/settings/company")["json"]
            rep["logo_survives_name_save"] = after.get("logo_data_url") == TINY_PNG and after.get("name_ar") == "شركة دخان QA"
            pg.screenshot(path=str(SHOTS / "_smoke_settings.png"))
            call(pg, "PUT", "/settings/company", {"name_ar": before.get("name_ar"), "logo_data_url": before.get("logo_data_url")})
            ctx.close()
        finally:
            br.close()
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    bad = [k for k, v in rep.items() if isinstance(v, bool) and not v]
    print(f"FAILED: {bad}" if bad else "ALL OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
