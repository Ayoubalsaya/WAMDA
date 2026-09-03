"""§٩ المرحلة ١٢ — تحديد معدل مسارات الدخول (الموظف والبوابة، حدّان منفصلان).

يُثبِت أن الحدّ يُطبَّق على تسجيل الدخول فقط ولا يمسّ طلبات القراءة.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import get_db
from app.main import app
from app.security.rate_limit import RateLimitedError, RateLimiter


# ── الوحدة ───────────────────────────────────────────────────────────


def test_rate_limiter_allows_up_to_max_then_blocks():
    rl = RateLimiter(max_hits=3, window_seconds=60)
    for i in range(3):
        rl.hit("1.2.3.4", now=1000.0 + i)
    with pytest.raises(RateLimitedError) as exc:
        rl.hit("1.2.3.4", now=1003.0)
    assert exc.value.retry_after_seconds > 0


def test_rate_limiter_window_slides():
    rl = RateLimiter(max_hits=2, window_seconds=60)
    rl.hit("ip", now=0.0)
    rl.hit("ip", now=1.0)
    with pytest.raises(RateLimitedError):
        rl.hit("ip", now=2.0)
    # بعد تجاوز النافذة — مسموح مجدداً
    rl.hit("ip", now=100.0)


def test_rate_limiter_keys_are_independent():
    rl = RateLimiter(max_hits=1, window_seconds=60)
    rl.hit("a", now=0.0)
    rl.hit("b", now=0.0)  # مفتاح آخر — لا يتأثر
    with pytest.raises(RateLimitedError):
        rl.hit("a", now=1.0)


# ── التكامل عبر HTTP ─────────────────────────────────────────────────


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


def test_staff_login_blocked_after_max_attempts_with_retry_after(client):
    limit = settings.login_rate_limit_max
    for _ in range(limit):
        r = client.post("/auth/login", json={"username": "qa_nobody", "password": "x"})
        assert r.status_code == 401  # اسم خطأ — لكن المحاولة تُحتسَب

    blocked = client.post("/auth/login", json={"username": "qa_nobody", "password": "x"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_portal_login_limit_is_more_lenient_than_staff(client):
    """العميل من هاتف بشبكة متغيّرة — حدّه أوسع من الموظف."""
    assert settings.portal_login_rate_limit_max > settings.login_rate_limit_max

    # عند حدّ الموظف بالضبط، البوابة لا تزال تقبل
    for _ in range(settings.login_rate_limit_max + 1):
        r = client.post("/portal/login", json={"code": "QA-NOBODY", "password": "x"})
        assert r.status_code in (401, 422)  # ليس 429 بعد


def test_read_requests_are_never_rate_limited(client):
    for _ in range(settings.login_rate_limit_max + 20):
        assert client.get("/health").status_code == 200


def test_limit_recovers_after_window_elapses(client, monkeypatch):
    """اختبار حيّ: تجاوز الحدّ → ٤٢٩ → مرور النافذة → يعود للعمل.
    الزمن مُحقن عبر `system_clock` فلا انتظار فعلي."""
    from datetime import datetime, timedelta, timezone

    from app.security import deps

    base = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(deps, "system_clock", lambda: base)
    for _ in range(settings.login_rate_limit_max):
        assert client.post("/auth/login", json={"username": "qa_x", "password": "x"}).status_code == 401
    assert client.post("/auth/login", json={"username": "qa_x", "password": "x"}).status_code == 429

    # بعد تجاوز النافذة بثانية — مسموح مجدداً
    later = base + timedelta(seconds=settings.login_rate_limit_window_seconds + 1)
    monkeypatch.setattr(deps, "system_clock", lambda: later)
    assert client.post("/auth/login", json={"username": "qa_x", "password": "x"}).status_code == 401


def test_key_read_from_forwarded_header_when_proxy_trusted(client, monkeypatch):
    """خلف nginx (`TRUST_PROXY_HEADERS=true`): العنوان من `X-Real-IP`/
    `X-Forwarded-For` لا من الاتصال المباشر — وإلا كل الطلبات من 127.0.0.1
    وتُقفَل على الجميع."""
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    limit = settings.login_rate_limit_max

    # العميل أ يستنفد حدّه
    for _ in range(limit):
        r = client.post("/auth/login", json={"username": "qa_x", "password": "x"},
                        headers={"X-Real-IP": "203.0.113.7"})
        assert r.status_code == 401
    assert client.post("/auth/login", json={"username": "qa_x", "password": "x"},
                       headers={"X-Real-IP": "203.0.113.7"}).status_code == 429

    # العميل ب (عنوان آخر) — غير متأثر، رغم نفس اتصال السيرفر المباشر
    assert client.post("/auth/login", json={"username": "qa_x", "password": "x"},
                       headers={"X-Real-IP": "198.51.100.42"}).status_code == 401

    # ترويسة X-Forwarded-For — يُؤخَذ الأخير (النظير المباشر كما ألحقه nginx)
    for _ in range(limit):
        client.post("/auth/login", json={"username": "qa_x", "password": "x"},
                    headers={"X-Forwarded-For": "1.1.1.1, 198.51.100.99"})
    assert client.post("/auth/login", json={"username": "qa_x", "password": "x"},
                       headers={"X-Forwarded-For": "1.1.1.1, 198.51.100.99"}).status_code == 429


def test_forwarded_headers_ignored_when_proxy_not_trusted(client):
    """الافتراض `trust_proxy_headers=False`: لا نثق بأي ترويسة وكيل —
    مفاتيح مختلفة لا تُنشئ دلاءً منفصلة (كلها الاتصال المباشر)، فلا يستطيع
    مهاجم تجاوز الحدّ بتزوير `X-Forwarded-For`."""
    assert settings.trust_proxy_headers is False
    limit = settings.login_rate_limit_max
    for i in range(limit):
        client.post("/auth/login", json={"username": "qa_x", "password": "x"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}"})
    # رغم تغيّر الترويسة كل مرة — نفس الدلو، فالتالي محظور
    assert client.post("/auth/login", json={"username": "qa_x", "password": "x"},
                       headers={"X-Forwarded-For": "10.9.9.9"}).status_code == 429
