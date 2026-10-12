"""شاشة الدخول (٢٠٢٦-١٠-١٢): الرسالة بالعدد المتبقّي تُعرض كما هي، وعند الإيقاف المؤقت عدّاد تنازلي حيّ «د:ثث» (لا ثوانٍ خام)
والإرسال معطَّل حتى ينتهي. الخادم حقيقي والاستجابة معترَضة في المتصفح لتحديد `Retry-After` بدقة."""

from __future__ import annotations

import json
import re

import pytest

from tests.ui_support import live_server  # noqa: F401  (الـfixture تُلتقَط بالاسم)


@pytest.fixture()
def login_page(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge")
        except Exception:
            try:
                browser = p.chromium.launch()
            except Exception:
                pytest.skip("لا متصفح Playwright متاح")
        try:
            pg = browser.new_context(locale="ar").new_page()
            pg.goto(live_server + "/")
            pg.wait_for_selector("#username")
            yield pg
        finally:
            browser.close()


def _fulfill(pg, status: int, detail: str, headers: dict | None = None):
    pg.route("**/auth/login", lambda route: route.fulfill(
        status=status, content_type="application/json", headers=headers or {}, body=json.dumps({"detail": detail})))


def _submit(pg):
    pg.fill("#username", "qa_user")
    pg.fill("#password", "x")
    pg.click("button[type=submit]")


def test_attempts_left_message_is_shown_verbatim(login_page):
    pg = login_page
    msg = "اسم المستخدم أو كلمة المرور غير صحيحة — بقيت 3 محاولات قبل الإيقاف المؤقت"
    _fulfill(pg, 401, msg)
    _submit(pg)
    pg.wait_for_selector(".alert-critical")
    assert pg.locator(".alert-critical").inner_text().strip() == msg


def test_rate_limit_shows_live_countdown_and_disables_submit(login_page):
    pg = login_page
    _fulfill(pg, 429, "طلبات كثيرة — حاول بعد دقيقتان و5 ثوانٍ", {"Retry-After": "125"})
    _submit(pg)
    notice = pg.locator('[role="alert"]')
    notice.wait_for()
    first = notice.locator("strong").inner_text().strip()
    assert re.fullmatch(r"2:0[0-5]|1:5\d", first), first      # «د:ثث»، لا «125»
    assert "125" not in notice.inner_text()
    assert pg.locator("button[type=submit]").is_disabled()
    pg.wait_for_timeout(1500)
    later = notice.locator("strong").inner_text().strip()
    assert later != first                                     # العدّاد يتحرّك
    # يُحسب تنازلياً بالثواني
    def secs(t: str) -> int:
        m, s = t.split(":")
        return int(m) * 60 + int(s)
    assert secs(later) < secs(first)


def test_account_lock_uses_the_same_countdown(login_page):
    pg = login_page
    _fulfill(pg, 423, "الحساب مقفل مؤقتاً بعد محاولات فاشلة — حاول بعد 14 دقيقة", {"Retry-After": "840"})
    _submit(pg)
    notice = pg.locator('[role="alert"]')
    notice.wait_for()
    assert "الحساب مقفل" in notice.inner_text()
    assert re.fullmatch(r"1[34]:\d\d", notice.locator("strong").inner_text().strip())
