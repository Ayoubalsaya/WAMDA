"""الرموز الاحتياطية بمتصفح حقيقي (٢٠٢٦-١٠-٠٣): إعداد المصادقة ← عرض الرموز (إلزامي) ← خروج ← دخول برمز ← رفض نفس الرمز ثانية."""

from __future__ import annotations

import pyotp
import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Session as SessionModel, User
from app.models.enums import SessionSubjectType
from app.security.passwords import hash_password
from tests import factories as f
from tests.ui_support import live_server  # noqa: F401

PASSWORD = "QaBackup!Pass9"


@pytest.fixture()
def fresh_user():
    """مدير بلا جهاز مصادقة (أول دخول)، يُنظَّف في النهاية."""
    username = f"qa_bk_{f.uid()[:8]}"
    db = SessionLocal()
    try:
        user = User(username=username, full_name="QA backup codes", role="ADMIN")
        user.password_hash = hash_password(PASSWORD)
        user.is_active, user.must_change_password = True, False
        db.add(user)
        db.commit()
        user_id = user.id
    finally:
        db.close()
    yield username
    db = SessionLocal()
    try:
        db.execute(SessionModel.__table__.delete().where(
            (SessionModel.subject_type == SessionSubjectType.USER) & (SessionModel.subject_id == user_id)))
        # audit_log أحادي الإضافة: لا حذف؛ المستخدم يُعطَّل إن تعذّر حذفه
        db.execute(__import__("sqlalchemy").text("DELETE FROM user_backup_codes WHERE user_id = :u"), {"u": user_id})
        u = db.get(User, user_id)
        try:
            db.delete(u)
            db.commit()
        except Exception:
            db.rollback()
            u = db.get(User, user_id)
            u.is_active = False
            db.commit()
    finally:
        db.close()


def _browser(p):
    try:
        return p.chromium.launch(channel="msedge")
    except Exception:
        try:
            return p.chromium.launch()
        except Exception:
            pytest.skip("لا متصفح Playwright متاح")


def test_setup_shows_codes_then_login_with_a_code_works_once(live_server, fresh_user):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _browser(p)
        pg = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ar").new_page()
        pg.goto(live_server + "/", wait_until="networkidle")
        pg.fill("#username", fresh_user)
        pg.fill("#password", PASSWORD)
        pg.click("button:has-text('دخول')")
        pg.wait_for_selector(".totp-secret-code", timeout=20000)
        secret = pg.inner_text(".totp-secret-code").strip()
        pg.fill("#totp", pyotp.TOTP(secret).now())
        pg.click("button:has-text('تأكيد')")

        # ١) تُعرض الرموز إلزامياً مع التحذير، ولا دخول للنظام قبل الإقرار
        pg.wait_for_selector("[data-testid=backup-codes-panel]", timeout=20000)
        assert "لن تظهر هذه الرموز مرة أخرى" in pg.inner_text("[data-testid=backup-codes-panel]")
        assert pg.locator("nav.sidebar").count() == 0
        codes = [t.strip() for t in pg.locator("[data-testid=backup-codes-list] li").all_inner_texts()]
        assert len(codes) == 10 and len(set(codes)) == 10
        assert pg.locator("button:has-text('نسخ الرموز')").count() == 1 and pg.locator("button:has-text('طباعة')").count() == 1
        assert pg.locator("button:has-text('متابعة إلى النظام')").is_disabled()
        pg.check("[data-testid=backup-codes-panel] input[type=checkbox]")
        pg.click("button:has-text('متابعة إلى النظام')")
        pg.wait_for_selector("nav.sidebar", timeout=20000)

        # ٢) الإعدادات ← الأمان: العدد المتبقّي ١٠ بلا رموز معروضة
        pg.click("button[title^='الإعدادات']")
        pg.click("button:has-text('الأمان')")
        pg.wait_for_selector("[data-testid=backup-codes-remaining]")
        assert "10 من 10" in pg.inner_text("[data-testid=backup-codes-remaining]").replace("١٠", "10")
        assert pg.locator("[data-testid=backup-codes-list]").count() == 0

        # ٣) خروج ثم دخول بكلمة المرور + رمز احتياطي
        pg.click("button:has-text('خروج')")
        pg.wait_for_selector("#username")

        def login_with(code: str):
            pg.fill("#username", fresh_user)
            pg.fill("#password", PASSWORD)
            pg.click("button:has-text('دخول')")
            pg.wait_for_selector("#totp", timeout=20000)
            pg.click("button:has-text('استخدم رمزاً احتياطياً')")
            pg.fill("#backup-code", code)
            pg.click("button:has-text('تأكيد')")

        login_with(codes[0])
        pg.wait_for_selector("nav.sidebar", timeout=20000)
        pg.click("button:has-text('خروج')")
        pg.wait_for_selector("#username")

        # ٤) نفس الرمز مرفوض في المرة الثانية، ولا دخول
        login_with(codes[0])
        pg.wait_for_selector(".alert-critical", timeout=20000)
        assert "سبق استعماله" in pg.inner_text(".alert-critical")
        assert pg.locator("nav.sidebar").count() == 0

        # ٥) رمز آخر يعمل، والمتبقّي ٨
        pg.fill("#backup-code", codes[1])
        pg.click("button:has-text('تأكيد')")
        pg.wait_for_selector("nav.sidebar", timeout=20000)
        db = SessionLocal()
        try:
            from app.security import backup_codes

            user = db.execute(select(User).where(User.username == fresh_user)).scalar_one()
            assert backup_codes.remaining(db, user_id=user.id) == 8
        finally:
            db.close()
        browser.close()
