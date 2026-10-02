"""اختبار انحدار بمتصفح حقيقي: **القيمة المرسلة = القيمة المعروضة** في كل حقول
المبالغ والأسعار بكل تبويبات دفتر اليومية (٢٠٢٦-١٠-٠٢، ملاحظة مالك: الحقل كان
يعرض ٩٫٠٥ لكن الخطأ المعروض يقول إن الخادم استلم `cost_rate="0"`).

السبب الجذري المُثبَت: ردّ ٤٢٢ لمحاولة سابقة (cost_rate=0) كان يبقى ظاهراً بجوار
حقل صُحِّح إلى ٩٫٠٥ (الحالة والإرسال سليمان). وصنف قريب منه: إدخال أرقام عربية
أو نص غير رقمي يرمي `DecimalError` داخل معاينة الصرافة فتسقط الواجهة كلها.

الاختبار يعمل على النسخة المبنية (`npm run build` → app/static/app) من خادم uvicorn
مؤقت على منفذ حر؛ طلبات الكتابة `/operations/*` تُعترَض وتُرَدّ بـ٤٢٢ مُصطنَع فلا
يُرحَّل أي قيد — فقط يُنشأ مستخدم وعميل QA مؤقتان يُنظَّفان بعده. يُتخطّى إن غابت
Playwright أو المتصفح أو النسخة المبنية.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pyotp
import pytest
from sqlalchemy import select

pytest.importorskip("playwright.sync_api")

from app.database import SessionLocal  # noqa: E402
from app.models import Client, Session as SessionModel, User  # noqa: E402
from app.models.enums import SessionSubjectType  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402
from tests import factories as f  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIST_INDEX = ROOT / "app" / "static" / "app" / "index.html"
pytestmark = pytest.mark.skipif(not DIST_INDEX.exists(), reason="النسخة المبنية للواجهة غير موجودة (npm run build)")

QA_PASS = "QaNum!Pass9"
QA_SECRET = "JBSWY3DPEHPK3PXP"

TAB_LABEL = {
    "RECEIPT": "قبض", "PAYMENT": "صرف", "EXCHANGE": "صرافة", "CASH_TRANSFER": "تحويل بعمولة",
    "REMIT_OUT": "إرسال خارجي", "EXPENSE": "مصروف", "SWIFT_OUT": "سويفت خروج", "SWIFT_IN": "سويفت وصول",
    "SWIFT_RETURN": "سويفت مرتجع", "LOCAL_MOVE": "نقل داخلي", "OPENING": "رصيد افتتاحي", "ADJUSTMENT": "تسوية",
}
LEVEL2 = {"SWIFT_OUT", "SWIFT_IN", "SWIFT_RETURN", "LOCAL_MOVE", "OPENING", "ADJUSTMENT"}
NEEDS_CLIENT = {"RECEIPT", "PAYMENT", "EXCHANGE", "CASH_TRANSFER", "REMIT_OUT", "SWIFT_RETURN"}
DISTINCT_VALUES = ["11.11", "22.22", "33.33", "44.44", "55.55", "66.66"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    port = _free_port()
    env = {**os.environ, "LOGIN_RATE_LIMIT_MAX": "1000", "PORTAL_LOGIN_RATE_LIMIT_MAX": "1000"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            pytest.skip("تعذّر تشغيل خادم مؤقت")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def qa_identity():
    """مدير + عميل QA مُلتزَمان فعلاً (الخادم المؤقت اتصال قاعدة آخر)، يُنظَّفان في النهاية."""
    username = f"qa_num_{f.uid()[:8]}"
    db = SessionLocal()
    try:
        user = User(username=username, full_name="QA numeric fields", role="ADMIN")
        user.password_hash = hash_password(QA_PASS)
        user.is_active, user.must_change_password = True, False
        user.totp_secret = QA_SECRET
        db.add(user)
        code = f"QA-NUM-{f.uid()[:6].upper()}"
        client = Client(code=code, name_ar=f"عميل رقمي {code}", search_name=f"عميل رقمي {code}", credit_allowed=False)
        db.add(client)
        db.commit()
        info = {"username": username, "client_code": code}
    finally:
        db.close()
    yield info
    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if user:
            db.execute(SessionModel.__table__.delete().where(
                (SessionModel.subject_type == SessionSubjectType.USER) & (SessionModel.subject_id == user.id)))
            try:
                db.delete(user)
                db.commit()
            except Exception:
                db.rollback()
                user = db.execute(select(User).where(User.username == username)).scalar_one()
                user.is_active = False
                db.commit()
        client = db.execute(select(Client).where(Client.code == info["client_code"])).scalar_one_or_none()
        if client:
            client.is_active = False
            db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def journal_page(live_server, qa_identity):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge")
        except Exception:
            try:
                browser = p.chromium.launch()
            except Exception:
                pytest.skip("لا متصفح Playwright متاح")
        ctx = browser.new_context(viewport={"width": 1440, "height": 1500}, locale="ar")
        pg = ctx.new_page()
        sent: list[dict] = []

        def stub(route):
            req = route.request
            if req.method == "POST" and "/operations/" in req.url:
                sent.append({"url": req.url, "body": json.loads(req.post_data or "{}")})
                route.fulfill(status=422, content_type="application/json", body=json.dumps({"detail": "رفض مُصطنَع (اختبار)"}))
            else:
                route.continue_()

        pg.route("**/operations/**", stub)
        pg.goto(live_server + "/", wait_until="networkidle")
        pg.fill("#username", qa_identity["username"])
        pg.fill("#password", QA_PASS)
        pg.click("button:has-text('دخول')")
        pg.wait_for_selector("#totp", timeout=20000)
        pg.fill("#totp", pyotp.TOTP(QA_SECRET).now())
        pg.click("button:has-text('تأكيد')")
        pg.wait_for_selector("nav.sidebar")
        pg.click("button[title^='دفتر اليومية']")
        pg.wait_for_selector(".journal-col-center")
        pg.wait_for_timeout(800)
        pg.sent = sent  # type: ignore[attr-defined]
        pg.client_code = qa_identity["client_code"]  # type: ignore[attr-defined]
        yield pg
        browser.close()


def _composer(pg):
    return pg.locator(".journal-col-center")


def _open_tab(pg, op: str):
    comp = _composer(pg)
    rx = re.compile(rf"^\s*{re.escape(TAB_LABEL[op])}\s*$")
    btn = comp.locator("button").filter(has_text=rx).first
    if not btn.is_visible():
        comp.locator("button").filter(has_text=re.compile(r"^\s*المزيد\s*$")).first.click()
    btn.click()
    pg.wait_for_timeout(250)


def _select_client(pg):
    pg.fill("#client-search", pg.client_code)
    pg.locator(".client-result", has_text=pg.client_code).first.click()
    pg.wait_for_timeout(400)


def _decimal_inputs(pg):
    return _composer(pg).locator('.composer-panel input[inputmode="decimal"]')


def _save(pg):
    n = len(pg.sent)
    _composer(pg).get_by_role("button", name="حفظ وترحيل", exact=True).click()
    pg.wait_for_timeout(500)
    return pg.sent[n:]


def _numeric_values(payload: dict) -> list[str]:
    return sorted(v for v in payload.values() if isinstance(v, str) and re.fullmatch(r"\d+\.\d+", v))


SCENARIOS = [
    ("RECEIPT", None), ("PAYMENT", None), ("EXCHANGE", "CLIENT"), ("EXCHANGE", "TREASURY"),
    ("CASH_TRANSFER", None), ("REMIT_OUT", None), ("EXPENSE", None), ("SWIFT_OUT", None), ("SWIFT_IN", None),
    ("LOCAL_MOVE", None), ("OPENING", None), ("ADJUSTMENT", None),
]


@pytest.mark.parametrize("op,scope", SCENARIOS, ids=[f"{o}-{s}" if s else o for o, s in SCENARIOS])
def test_every_numeric_field_sent_equals_displayed(journal_page, op, scope):
    """كل قيمة رقمية معروضة في أي حقل مبلغ/سعر تظهر حرفياً في الطلب، ولا قيمة
    رقمية تُرسَل لم تكن معروضة (لا `0` ولا تحويل صامت)."""
    pg = journal_page
    _open_tab(pg, op)
    if op in NEEDS_CLIENT:
        _select_client(pg)
    if scope == "TREASURY":
        _composer(pg).locator("button").filter(has_text="خزينة").first.click()
        pg.wait_for_timeout(300)

    inputs = _decimal_inputs(pg)
    count = inputs.count()
    assert count >= 1, f"لا حقول رقمية في {op}"
    displayed = []
    for i in range(count):
        el = inputs.nth(i)
        value = DISTINCT_VALUES[i]
        el.fill("")
        el.press_sequentially(value, delay=20)  # ضغطات حقيقية لا تعيين مباشر
        displayed.append(el.input_value())
    assert displayed == DISTINCT_VALUES[:count], "الحقل لا يعرض ما كُتب"

    requests = _save(pg)
    assert len(requests) == 1, f"{op}: لم يُرسَل طلب واحد ({len(requests)})"
    sent_values = _numeric_values(requests[0]["body"])
    assert sent_values == sorted(displayed), f"{op}: المعروض {sorted(displayed)} ≠ المُرسَل {sent_values}"


def test_arabic_digits_are_normalised_not_a_crash(journal_page):
    """أرقام عربية-هندية وفاصلة «٫»: تُحوَّل في الحقل نفسه إلى ٩٫٠٥ لاتينية، فالمعروض
    = المُرسَل، والواجهة لا تسقط (كان DecimalError يُفرغ الصفحة)."""
    pg = journal_page
    _open_tab(pg, "EXCHANGE")
    _select_client(pg)
    comp = _composer(pg)
    inputs = _decimal_inputs(pg)
    inputs.nth(0).fill("")
    inputs.nth(0).press_sequentially("٩٫٠٥", delay=20)
    assert inputs.nth(0).input_value() == "9.05"
    assert pg.evaluate("document.getElementById('root').children.length") > 0
    assert comp.is_visible()
    requests = _save(pg)
    assert requests and requests[0]["body"]["amount"] == "9.05"


@pytest.mark.parametrize("raw", ["1,000", "9,05", "abc", "9.05.1"])
def test_invalid_number_is_flagged_not_sent_and_does_not_crash(journal_page, raw):
    pg = journal_page
    _open_tab(pg, "EXPENSE")
    inputs = _decimal_inputs(pg)
    inputs.nth(0).fill("")
    inputs.nth(0).press_sequentially(raw, delay=20)
    assert pg.evaluate("document.getElementById('root').children.length") > 0, "سقطت الواجهة"
    assert _composer(pg).locator("[role=alert].field-error").count() == 1  # رسالة عربية تحت الحقل
    assert _save(pg) == []  # لا طلب بقيمة غير صالحة
    assert "المبلغ" in _composer(pg).locator(".form-guide[role=alert]").first.inner_text()  # رسالة عربية باسم الحقل


def test_stale_server_error_disappears_when_the_field_is_corrected(journal_page):
    """السيناريو الأصلي: محاولة أولى بسعر تكلفة ٠ ← رفض ← تصحيح الحقل إلى ٩٫٠٥ ←
    الخطأ القديم يجب ألا يبقى ظاهراً بجوار الحقل المُصحَّح."""
    pg = journal_page
    _open_tab(pg, "EXCHANGE")
    _select_client(pg)
    comp = _composer(pg)
    inputs = _decimal_inputs(pg)  # المبلغ، سعر العميل، سعر التكلفة
    for i, v in enumerate(["100", "9.80", "0"]):
        inputs.nth(i).fill("")
        inputs.nth(i).press_sequentially(v, delay=20)
    first = _save(pg)
    assert first and first[0]["body"]["cost_rate"] == "0"
    assert comp.locator("[role=alert]").count() == 1, "الخطأ يجب أن يظهر بعد الرفض"

    inputs.nth(2).fill("")
    inputs.nth(2).press_sequentially("9.05", delay=20)
    assert inputs.nth(2).input_value() == "9.05"
    assert comp.locator("[role=alert]").count() == 0, "بقي خطأ المحاولة السابقة بجوار الحقل المُصحَّح"
    second = _save(pg)
    assert second and second[0]["body"]["cost_rate"] == "9.05"
