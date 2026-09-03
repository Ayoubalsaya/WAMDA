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
