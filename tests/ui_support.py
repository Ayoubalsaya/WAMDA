"""بنية مشتركة لاختبارات الواجهة بمتصفح حقيقي (`test_ui_*.py`): خادم uvicorn مؤقت على منفذ
حر، مستخدم وعميل QA مؤقتان، متصفح Playwright مسجَّل الدخول، واعتراض طلبات الكتابة
`/operations/*` بأوضاع (`pg.mode`): `stub` (٤٢٢ نصي مُصطنَع) · `real` (الخادم الحقيقي) ·
`raw422` (قائمة Pydantic خام مُحقَنة) · `abort` (انقطاع شبكة) · `html502` (رد غير JSON).
يُتخطّى كل شيء إن غابت Playwright أو المتصفح أو النسخة المبنية (`npm run build`).
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
from app.models import Client, Partner, Session as SessionModel, User  # noqa: E402
from app.models.enums import SessionSubjectType  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402
from tests import factories as f  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIST_INDEX = ROOT / "app" / "static" / "app" / "index.html"

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
    if not DIST_INDEX.exists():
        pytest.skip("النسخة المبنية للواجهة غير موجودة (npm run build)")
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
        client = Client(code=code, name_ar=f"عميل رقمي {code}", search_name=f"عميل رقمي {code}")
        db.add(client)
        partner = Partner(code=f"QA-P-{f.uid()[:6].upper()}", name_ar="شريك اختبار الواجهة", country="تركيا")
        db.add(partner)
        db.commit()
        info = {"username": username, "client_code": code, "partner_code": partner.code}
    finally:
        db.close()
    yield info
    db = SessionLocal()
    try:
        # تنظيف كامل لبيانات QA (عملاء `QA-…` وقيودهم ومستخدمو `qa_…`) — اختبارات المتصفح قد تُنشئ عملاء وقيوداً
        # حقيقية على قاعدة الاختبار (الإضافة السريعة + ترحيل). قاعدة الاختبار حصراً (conftest يضمن اسمها `_test`).
        from app.cli import purge_demo_data
        from app.config import settings

        assert settings.database_url.rsplit("/", 1)[1].split("?")[0].endswith("_test")
        purge_demo_data._purge(db)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
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
        partner = db.execute(select(Partner).where(Partner.code == info["partner_code"])).scalar_one_or_none()
        if partner:
            db.delete(partner)
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

        pg.mode = "stub"  # type: ignore[attr-defined]

        def stub(route):
            req = route.request
            if req.method != "POST" or "/operations/" not in req.url:
                route.continue_()
                return
            sent.append({"url": req.url, "body": json.loads(req.post_data or "{}")})
            mode = pg.mode  # type: ignore[attr-defined]
            if mode == "real":
                route.continue_()
            elif mode == "raw422":  # شكل Pydantic الخام القديم — يجب ألا يصل الشاشة أبداً
                route.fulfill(status=422, content_type="application/json", body=json.dumps({"detail": [
                    {"type": "greater_than", "loc": ["body", "cost_rate"], "msg": "Input should be greater than 0",
                     "input": "0", "ctx": {"gt": 0}}]}))
            elif mode == "abort":
                route.abort()
            elif mode == "html502":
                route.fulfill(status=502, content_type="text/html", body="<html><body>502 Bad Gateway</body></html>")
            else:
                route.fulfill(status=422, content_type="application/json", body=json.dumps({"detail": "رفض مُصطنَع (اختبار)"}))

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


