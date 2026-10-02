"""تحقُّق حيّ من متصفح حقيقي (Chromium) لتدفُّق إدارة بوابة العميل الجديد
(§٧-٦، ٢٠٢٦-١٠-٠٢): إنشاء دعوة ← نسخ الرابط ← فتحه في سياق خاص منفصل
(يحاكي جهاز العميل) ← تعيين كلمة المرور ← دخول البوابة ← محاولة فتح نفس
الرابط ثانيةً (مرفوض) ← تعطيل من النظام ← جلسة العميل القائمة تنتهي فوراً.

يبني على النسخة المبنية فعلياً (`npm run build` → app/static/app)، مخدومة
من uvicorn ٨٠٠٠ بلا --reload — لا 5173 وحده (نفس قاعدة بقية سكربتات QA).

الاستخدام:
    PYTHONPATH=. venv/Scripts/python.exe scripts/qa_portal_invite_flow.py
"""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pyotp
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Client, User
from app.security.passwords import hash_password

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "design" / "journal-redesign-shots" / "portal-invite-flow"
SHOTS.mkdir(parents=True, exist_ok=True)

QA_USER, QA_PASS, QA_SECRET = "qa_jrnl_admin", "QaJrnl!Pass9", "JBSWY3DPEHPK3PXP"
BASE = "http://127.0.0.1:8000"


def setup_admin() -> None:
    """يتأكد من وجود مدير QA — نفس حساب qa_journal_redesign.py/qa_webkit_check.py،
    يُنشَأ هنا فقط إن غاب (لا حذف، لا إعادة إنشاء)."""
    db = SessionLocal()
    try:
        u = db.execute(select(User).where(User.username == QA_USER)).scalar_one_or_none()
        if u is None:
            u = User(username=QA_USER, full_name="QA journal redesign", role="ADMIN")
            db.add(u)
        u.password_hash = hash_password(QA_PASS)
        u.role, u.is_active, u.must_change_password = "ADMIN", True, False
        u.totp_secret, u.failed_attempts, u.locked_until = QA_SECRET, 0, None
        db.commit()
    finally:
        db.close()


def make_fresh_client() -> str:
    """عميل جديد بلا أي تاريخ بوابة — كود فريد كل تشغيلة كي يبدأ الاختبار
    فعلياً من NOT_ENABLED، لا إعادة تدوير فِكستور قديم قد يحمل حالة سابقة."""
    code = f"QA-PINV-{uuid.uuid4().hex[:8].upper()}"
    db = SessionLocal()
    try:
        c = Client(code=code, name_ar="محمد القا الاختبار", search_name="محمد القا الاختبار", credit_allowed=False, phone="+218910000001")
        db.add(c)
        db.commit()
    finally:
        db.close()
    return code


def staff_login(pg) -> None:
    pg.goto(f"{BASE}/static/app/index.html", wait_until="networkidle")
    pg.wait_for_selector("#username")
    pg.fill("#username", QA_USER)
    pg.fill("#password", QA_PASS)
    pg.click("button:has-text('دخول')")
    pg.wait_for_selector("#totp", timeout=10000)
    pg.fill("#totp", pyotp.TOTP(QA_SECRET).now())
    pg.click("button:has-text('تأكيد')")
    pg.wait_for_selector("nav.sidebar")


def open_client(pg, code: str) -> None:
    pg.click("button[title^='العملاء']")
    pg.wait_for_selector(".clients-screen")
    pg.fill(".clients-screen input", code)
    pg.wait_for_selector(f"tr.clients-row:has-text('{code}')", timeout=5000)
    pg.click(f"tr.clients-row:has-text('{code}')")
    pg.wait_for_selector(".client-detail-header")


def main() -> int:
    from playwright.sync_api import sync_playwright

    setup_admin()
    code = make_fresh_client()
    report: dict = {"client_code": code}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            staff_ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ar")
            staff = staff_ctx.new_page()
            staff_login(staff)
            open_client(staff, code)
            staff.screenshot(path=str(SHOTS / "01_not_enabled.png"))
            assert staff.locator("text=غير مفعّلة").count() > 0
            report["status_before"] = "NOT_ENABLED (confirmed on screen)"

            # ── تفعيل + إنشاء دعوة ──────────────────────────────────
            staff.click("button:has-text('تفعيل + إنشاء دعوة')")
            staff.wait_for_selector("text=لن يظهر هذا الرابط مرة أخرى", timeout=5000)
            staff.screenshot(path=str(SHOTS / "02_invite_revealed.png"))
            invite_url = staff.locator(".alert-warning .num").inner_text().strip()
            assert "#invite=" in invite_url
            report["invite_url_shape_ok"] = "#invite=" in invite_url and invite_url.startswith("http")
            token = invite_url.split("#invite=", 1)[1]

            # لا حاجة لإعادة تحميل الصفحة — المكوّن يُحدِّث الحالة داخلياً
            # فور الإجراء (لا توجّه URL لكل عميل في هذا النظام أصلاً).
            staff.wait_for_selector("text=دعوة معلّقة", timeout=5000)
            report["status_after_enable"] = "INVITE_PENDING (confirmed on screen)"
            staff.screenshot(path=str(SHOTS / "03_invite_pending.png"))

            # إغلاق لوحة الكشف لمرة واحدة — لا زرّي نسخ/واتساب بعدها، طلب مالك صريح
            staff.click("button[title='إغلاق']")
            staff.wait_for_timeout(200)
            report["copy_whatsapp_hidden_after_dismiss"] = (
                staff.locator("button:has-text('نسخ الرابط')").count() == 0
                and staff.locator("text=دعوة معلّقة").count() > 0
            )
            staff.screenshot(path=str(SHOTS / "03b_invite_pending_dismissed.png"))

            # ── سياق خاص منفصل يحاكي جهاز العميل ───────────────────
            client_ctx = browser.new_context(viewport={"width": 430, "height": 932}, locale="ar")
            client_pg = client_ctx.new_page()
            client_pg.goto(invite_url, wait_until="networkidle")
            client_pg.wait_for_selector("text=أهلاً", timeout=8000)
            client_pg.screenshot(path=str(SHOTS / "04_invite_accept_form.png"))

            new_password = "ClientChosen!789"
            client_pg.fill("#invite-password", new_password)
            client_pg.fill("#invite-confirm", new_password)
            client_pg.click("button:has-text('حفظ كلمة المرور')")
            client_pg.wait_for_selector("text=تم تعيين كلمة مرورك بنجاح", timeout=8000)
            client_pg.screenshot(path=str(SHOTS / "05_invite_accept_done.png"))
            report["invite_accept_ok"] = True

            client_pg.click("button:has-text('الدخول للبوابة الآن')")
            client_pg.wait_for_selector("#portal-code", timeout=8000)
            client_pg.fill("#portal-code", code)
            client_pg.fill("#portal-password", new_password)
            with client_pg.expect_response(lambda r: "/portal/login" in r.url) as ri:
                client_pg.click("button:has-text('دخول')")
            report["portal_login_status"] = ri.value.status
            client_pg.wait_for_selector(".portal-home", timeout=10000)
            client_pg.screenshot(path=str(SHOTS / "06_portal_home_after_invite.png"))
            report["portal_home_loaded"] = client_pg.locator(".portal-home").count() > 0

            # ── محاولة فتح نفس رابط الدعوة ثانيةً — مرفوض ───────────
            reuse_ctx = browser.new_context(viewport={"width": 430, "height": 932}, locale="ar")
            reuse_pg = reuse_ctx.new_page()
            reuse_pg.goto(invite_url, wait_until="networkidle")
            reuse_pg.wait_for_selector("text=رابط الدعوة غير صالح أو منتهٍ", timeout=8000)
            reuse_pg.screenshot(path=str(SHOTS / "07_invite_reuse_rejected.png"))
            report["invite_reuse_rejected"] = True
            reuse_ctx.close()

            # ── الموظف: الحالة صارت مفعّلة، ثم تعطيل (إعادة فتح ملف
            # العميل عبر التنقّل الطبيعي — لا توجّه URL لكل عميل هنا) ──
            open_client(staff, code)
            staff.wait_for_selector("text=مفعّلة", timeout=5000)
            assert staff.locator("text=مفعّلة").count() > 0
            report["status_after_accept"] = "ACTIVE (confirmed on screen)"
            staff.screenshot(path=str(SHOTS / "08_status_active.png"))

            staff.click("button:has-text('تعطيل')")
            staff.wait_for_selector("text=تعطيل البوابة؟")
            staff.click("button:has-text('تأكيد')")
            staff.wait_for_selector("text=معطّلة", timeout=5000)
            staff.screenshot(path=str(SHOTS / "09_status_disabled.png"))
            report["disabled_from_admin"] = True

            # ── جلسة العميل القائمة فعلاً تنتهي فوراً ───────────────
            client_pg.reload()
            client_pg.wait_for_selector("#portal-code", timeout=8000)
            client_pg.screenshot(path=str(SHOTS / "10_client_session_ended.png"))
            report["client_session_ended_immediately"] = client_pg.locator("#portal-code").count() > 0

            client_ctx.close()
            staff_ctx.close()
        finally:
            browser.close()

    import json

    print(json.dumps(report, ensure_ascii=False, indent=2))
    (SHOTS / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    failures = [k for k, v in report.items() if isinstance(v, bool) and not v]
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
