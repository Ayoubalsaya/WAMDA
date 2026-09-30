"""تحقُّق WebKit (محرّك Safari — ما يستخدمه عملاء بوابة العميل على آيفون
فعلياً) لِما تعذَّر اختباره سابقاً بسبب تعذُّر تثبيت المتصفح في تلك الجلسة:
حركة الكبسولة النابضة (SegmentedTabs) · بوابة العميل كاملة · عملية واحدة
حتى الترحيل. راجع docs/design/journal-redesign-plan.md وPROGRESS.md.

بيانات QA بالسابقة الموحَّدة، تُعاد نفس حسابات qa_journal_redesign.py:
مستخدم الموظف qa_jrnl_admin · عميل QA-JRNL-001 (كلاهما نشط من جلسة
سابقة، يُنشَأ هنا فقط إن غاب). عميل بوابة منفصل QA-PORTAL-001 بكلمة مرور
بوابة صريحة. لا حذف — نفس فلسفة الملف الشقيق.

الاستخدام:
    PYTHONPATH=. venv/Scripts/python.exe scripts/qa_webkit_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pyotp
from sqlalchemy import select

from decimal import Decimal

from app.database import SessionLocal
from app.engine import accounts_repo
from app.engine.clock import system_clock
from app.engine.operations import opening_balance
from app.models import Client, Session as SessionModel, User
from app.models.enums import ConfidenceLevel, OpeningSourceType, SessionSubjectType
from app.security.passwords import hash_password

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "design" / "journal-redesign-shots" / "webkit"

QA_USER, QA_PASS, QA_SECRET = "qa_jrnl_admin", "QaJrnl!Pass9", "JBSWY3DPEHPK3PXP"
QA_CLIENT_CODE = "QA-JRNL-001"
QA_PORTAL_CODE, QA_PORTAL_NAME = "QA-PORTAL-001", "عميل QA — بوابة WebKit"
QA_PORTAL_PASS = "QaPortal!9x"


def setup_db() -> None:
    db = SessionLocal()
    try:
        u = db.execute(select(User).where(User.username == QA_USER)).scalar_one_or_none()
        if u is None:
            u = User(username=QA_USER, full_name="QA journal redesign", role="ADMIN")
            db.add(u)
        u.password_hash = hash_password(QA_PASS)
        u.role, u.is_active, u.must_change_password = "ADMIN", True, False
        u.totp_secret, u.failed_attempts, u.locked_until = QA_SECRET, 0, None

        c = db.execute(select(Client).where(Client.code == QA_CLIENT_CODE)).scalar_one_or_none()
        if c is None:
            c = Client(code=QA_CLIENT_CODE, name_ar="عميل QA — دفتر اليومية", search_name="عميل QA", credit_allowed=False)
            db.add(c)
        c.is_active = True

        pc = db.execute(select(Client).where(Client.code == QA_PORTAL_CODE)).scalar_one_or_none()
        if pc is None:
            pc = Client(code=QA_PORTAL_CODE, name_ar=QA_PORTAL_NAME, search_name=QA_PORTAL_NAME, credit_allowed=False)
            db.add(pc)
        pc.is_active = True
        pc.portal_password_hash = hash_password(QA_PORTAL_PASS)
        pc.portal_must_change = False
        pc.portal_failed_attempts = 0
        pc.portal_locked_until = None
        db.commit()

        # رصيد حقيقي (لا كتابة مباشرة على account_balances) — بلا هذا لا
        # تظهر بطاقة رصيد ولا كشف حساب ولا زر طباعة في البوابة إطلاقاً
        # (بوابة العميل تعرض فقط عملات لها صفوف ClientBalance فعلية).
        # يبقى دائماً — فِكستور بوابة QA ثابت، لا يُعكَس كل تشغيل.
        account = accounts_repo.get_or_create_client_account(db, client=pc, currency_code="LYD", location_code="TRIPOLI")
        from app.models import AccountBalance
        bal_row = db.get(AccountBalance, account.id)
        if bal_row is None or bal_row.balance == 0:
            opening_balance.execute(
                db, account_code=account.code, currency_code="LYD", amount=Decimal("500.000"),
                is_debit=False,  # دائن يزيد رصيد حساب العميل (التزام) — مطابق قطبية القبض
                as_of_date=system_clock().date(), source_type=OpeningSourceType.VERIFIED,
                confidence=ConfidenceLevel.HIGH, approved_by=u.id, created_by=u.id, now=system_clock(),
                idempotency_key=f"qa-webkit-portal-opening-{pc.id}", source_note="فِكستور بوابة QA — WebKit",
            )
            db.commit()
    finally:
        db.close()


def teardown_db() -> str:
    db = SessionLocal()
    note = []
    try:
        u = db.execute(select(User).where(User.username == QA_USER)).scalar_one_or_none()
        if u:
            db.execute(SessionModel.__table__.delete().where(
                (SessionModel.subject_type == SessionSubjectType.USER) & (SessionModel.subject_id == u.id)
            ))
            db.commit()
        for code in (QA_CLIENT_CODE, QA_PORTAL_CODE):
            c = db.execute(select(Client).where(Client.code == code)).scalar_one_or_none()
            if c:
                c.is_active = False
                db.commit()
                note.append(f"{code} deactivated")
    finally:
        db.close()
    return ", ".join(note)


def check_capsule(pg, shots: Path) -> dict:
    """حركة الكبسولة على WebKit: تمدُّد منتصف الانتقال · نقر سريع متتالٍ ·
    أسهم RTL · prefers-reduced-motion. نفس الفحوص المُجراة سابقاً على
    Chromium (انظر PROGRESS.md)، هنا فقط للتأكّد من عدم اختلاف WebKit."""
    out: dict = {}
    pg.goto("https://localhost:5174/static/app/", wait_until="networkidle")
    pg.wait_for_selector("#username")
    pg.fill("#username", QA_USER)
    pg.fill("#password", QA_PASS)
    pg.click("button:has-text('دخول')")
    try:
        pg.wait_for_selector("#totp", timeout=8000)
    except Exception:
        pg.wait_for_timeout(5000)
        pg.click("button:has-text('دخول')")
        pg.wait_for_selector("#totp", timeout=20000)
    pg.fill("#totp", pyotp.TOTP(QA_SECRET).now())
    pg.click("button:has-text('تأكيد')")
    pg.wait_for_selector("nav.sidebar")
    pg.click("button[title^='دفتر اليومية']")
    pg.wait_for_selector(".journal-col-center")
    pg.wait_for_timeout(500)

    dock = pg.locator(".operation-dock").first

    # ١) تمدُّد منتصف الانتقال — لقطات متتالية بعد قفزة بعيدة (قبض ← مصروف)
    target = dock.get_by_role("tab", name="مصروف")
    target.click()
    for i, delay in enumerate([40, 90, 150, 220, 350]):
        pg.wait_for_timeout(delay if i == 0 else delay - [40, 90, 150, 220, 350][i - 1])
        pg.screenshot(path=str(shots / f"capsule_stretch_{i}_{delay}ms.png"),
                       clip={"x": 330, "y": 160, "width": 680, "height": 60})
    out["stretch_frames"] = "captured 5 frames — see capsule_stretch_*.png"

    # ٢) نقر سريع متتالٍ بلا انتظار استقرار — الكبسولة يجب ألا تعلق بين زرين
    labels = ["قبض", "صرف", "صرافة", "تحويل بعمولة", "إرسال خارجي", "مصروف"]
    for lbl in labels * 3:
        dock.get_by_role("tab", name=lbl).click(timeout=2000)
    pg.wait_for_timeout(500)
    active = dock.locator('[aria-selected="true"]').bounding_box()
    pill = dock.locator(".seg-pill").bounding_box()
    aligned = bool(active and pill and abs(active["x"] - pill["x"]) < 3 and abs(active["width"] - pill["width"]) < 3)
    out["rapid_clicks_aligned"] = aligned

    # ٣) الأسهم في RTL — من "قبض" (أول عنصر) عشرون ضغطة ArrowLeft
    dock.get_by_role("tab", name="قبض").click()
    pg.wait_for_timeout(300)
    dock.get_by_role("tab", name="قبض").focus()
    for _ in range(20):
        pg.keyboard.press("ArrowLeft")
    pg.wait_for_timeout(400)
    final_tab = dock.locator('[aria-selected="true"]').inner_text()
    # ٢٠ ضغطة، ٦ عناصر، RTL: ArrowLeft يزيد الفهرس (dir=1) — ٢٠ mod ٦ = ٢ → "صرافة"
    out["arrow_rtl_final_tab"] = final_tab.replace("\n", " ")
    out["arrow_rtl_correct"] = "صرافة" in final_tab

    # ٤) prefers-reduced-motion — قفزة فورية بلا تمدد
    pg.emulate_media(reduced_motion="reduce")
    dock.get_by_role("tab", name="مصروف").click()
    pg.wait_for_timeout(30)
    active2 = dock.locator('[aria-selected="true"]').bounding_box()
    pill2 = dock.locator(".seg-pill").bounding_box()
    out["reduced_motion_instant"] = bool(
        active2 and pill2 and abs(active2["x"] - pill2["x"]) < 3 and abs(active2["width"] - pill2["width"]) < 3)
    pg.emulate_media(reduced_motion="no-preference")
    pg.screenshot(path=str(shots / "capsule_final_state.png"))
    return out


def check_operation_post(pg, shots: Path) -> dict:
    """عملية واحدة (قبض) حتى الترحيل الفعلي، ثم عكسها."""
    pg.click("#client-search")
    pg.fill("#client-search", "QA-JRNL")
    pg.wait_for_selector(".client-result")
    pg.locator(".client-result", has_text=QA_CLIENT_CODE).first.click()
    pg.wait_for_timeout(300)

    composer = pg.locator(".journal-col-center")
    dock = composer.locator(".operation-dock").first
    dock.get_by_role("tab", name="قبض").click()
    pg.wait_for_timeout(200)

    def field(label: str):
        return composer.locator(".field").filter(has=pg.locator("label.field-label", has_text=label)).first

    field("العملة").locator("select").select_option("LYD")
    field("الموقع").locator("select").select_option("TRIPOLI")
    composer.locator("button.acct-picker-trigger").first.click()
    composer.locator(".acct-picker-row").first.click()
    composer.locator("#op-amount").fill("777")
    pg.wait_for_timeout(200)
    pg.screenshot(path=str(shots / "receipt_filled.png"))

    def pred(r):
        return r.request.method == "POST" and "/operations/receipt" in r.url

    with pg.expect_response(pred, timeout=20000) as ri:
        composer.get_by_role("button", name="حفظ وترحيل", exact=True).click()
    resp = ri.value
    result = {"status": resp.status, "body": resp.text()[:300]}
    if resp.ok:
        pg.wait_for_selector("text=/تم الترحيل/", timeout=10000)
        pg.screenshot(path=str(shots / "receipt_posted.png"))
        entry_no = resp.json()["entry_no"]
        eid = pg.evaluate("""async (no) => {
          const today = new Intl.DateTimeFormat('en-CA', {timeZone:'Africa/Tripoli'}).format(new Date());
          const r = await fetch('/journal/entries?date=' + today + '&include_reversed=false', {credentials:'include'});
          const rows = await r.json(); return rows.find(e => e.entry_no === no)?.id;
        }""", entry_no)
        if eid:
            cancel = pg.evaluate("""async (id) => {
              const csrf = decodeURIComponent((document.cookie.match(/(?:^|; )wamda_csrf=([^;]*)/)||[])[1]||'');
              const r = await fetch('/operations/' + id + '/cancel', {method:'POST', credentials:'include',
                headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body: JSON.stringify({reason:'QA WebKit — عكس'})});
              return r.status + ' ' + (await r.text()).slice(0, 150);
            }""", eid)
            result["cancel"] = cancel
    return result


def check_portal(pg, shots: Path) -> dict:
    out: dict = {}
    pg.goto("https://localhost:5174/static/app/portal.html", wait_until="networkidle")
    pg.wait_for_selector("#portal-code")
    pg.screenshot(path=str(shots / "portal_login.png"))
    pg.fill("#portal-code", QA_PORTAL_CODE)
    pg.fill("#portal-password", QA_PORTAL_PASS)
    with pg.expect_response(lambda r: "/portal/login" in r.url) as ri:
        pg.click("button:has-text('دخول')")
    login_resp = ri.value
    out["login_status"] = login_resp.status
    pg.wait_for_selector(".portal-home", timeout=10000)
    pg.wait_for_timeout(500)
    out["home_loaded"] = pg.locator(".portal-home").count() > 0
    out["balance_cards"] = pg.locator(".portal-balance-card").count()
    pg.screenshot(path=str(shots / "portal_home.png"))

    rows = pg.locator(".portal-location-row")
    if rows.count() > 0:
        rows.first.click()
        pg.wait_for_timeout(500)
        out["statement_visible"] = pg.locator(".portal-statement-card").count() > 0
        pg.screenshot(path=str(shots / "portal_statement.png"))

    # الطباعة: window.print() يجب ألا يُسقط استثناءً جافاسكربت (لا مطبعة
    # حقيقية في CI — التحقُّق أن النداء نفسه يعمل واتجاه/تنسيق الطباعة
    # المُعرَّف بـ@media print يُطبَّق فعلياً عبر محاكاة وسيط الطباعة).
    js_errors = []
    pg.on("pageerror", lambda e: js_errors.append(str(e)))
    pg.locator("button[aria-label='طباعة']").click()
    pg.wait_for_timeout(300)
    pg.emulate_media(media="print")
    pg.wait_for_timeout(200)
    out["print_topbar_hidden"] = pg.locator(".portal-topbar").evaluate("el => getComputedStyle(el).display") == "none"
    pg.screenshot(path=str(shots / "portal_print_preview.png"))
    pg.emulate_media(media="screen")
    out["print_js_errors"] = js_errors

    pg.click("button:has-text('خروج')")
    pg.wait_for_selector("#portal-code", timeout=10000)
    out["logout_ok"] = pg.locator("#portal-code").count() > 0
    return out


def main() -> int:
    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    setup_db()
    report: dict = {}
    try:
        with sync_playwright() as p:
            browser = p.webkit.launch()
            # ignore_https_errors: شهادة موقَّعة ذاتياً محلياً لهذا التحقق وحده
            # (انظر PROGRESS.md — WebKit يرفض كوكي Secure عبر HTTP فعلياً،
            # الإنتاج الحقيقي HTTPS بشهادة حقيقية فلا يُصادف هذا إطلاقاً).
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ar", ignore_https_errors=True)
            pg = ctx.new_page()

            report["capsule"] = check_capsule(pg, SHOTS)
            report["operation_post"] = check_operation_post(pg, SHOTS)

            portal_ctx = browser.new_context(
                viewport={"width": 430, "height": 932}, locale="ar", ignore_https_errors=True)  # iPhone 14 Pro-ish
            portal_pg = portal_ctx.new_page()
            report["portal"] = check_portal(portal_pg, SHOTS)

            browser.close()
    finally:
        report["teardown"] = teardown_db()

    import json
    print(json.dumps(report, ensure_ascii=False, indent=2))
    (SHOTS / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
