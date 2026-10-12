"""رسائل الدخول (٢٠٢٦-١٠-١٢): العدد المتبقّي بعد كل محاولة فاشلة، ومدّة الإيقاف بالدقائق والثواني (لا ثوانٍ خام)،
و`Retry-After` لعدّاد الواجهة، والمحاولة المرفوضة لا تُمدّد الإيقاف."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import get_db
from app.main import app
from app.security import deps
from app.security.login_messages import format_attempts_left_ar, format_wait_ar
from app.security.passwords import hash_password
from app.security.rate_limit import RateLimitedError, RateLimiter
from tests import factories as f

PASSWORD = "Sup3rSecret!1"


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


def _user_with_totp(db):
    user = f.make_user(db, role="ADMIN")
    user.password_hash = hash_password(PASSWORD)
    user.must_change_password = False
    user.totp_secret = pyotp.random_base32()
    db.flush()
    return user


# ── الصياغة ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("seconds,expected", [
    (787, "13 دقيقة و7 ثوانٍ"),
    (60, "دقيقة واحدة"),
    (61, "دقيقة واحدة وثانية واحدة"),
    (120, "دقيقتان"),
    (125, "دقيقتان و5 ثوانٍ"),
    (900, "15 دقيقة"),
    (1, "ثانية واحدة"),
    (2, "ثانيتان"),
    (45, "45 ثانية"),
    (180, "3 دقائق"),
])
def test_wait_is_minutes_and_seconds_never_raw_seconds(seconds, expected):
    assert format_wait_ar(seconds) == expected


@pytest.mark.parametrize("left,expected", [
    (7, "بقيت 7 محاولات قبل الإيقاف المؤقت"),
    (3, "بقيت 3 محاولات قبل الإيقاف المؤقت"),
    (2, "بقيت محاولتان قبل الإيقاف المؤقت"),
    (1, "بقيت محاولة واحدة قبل الإيقاف المؤقت"),
    (0, "لا محاولات متبقية قبل الإيقاف المؤقت"),
    (12, "بقيت 12 محاولة قبل الإيقاف المؤقت"),
])
def test_attempts_left_wording(left, expected):
    assert format_attempts_left_ar(left) == expected


# ── المحاولة المرفوضة لا تُمدّد الإيقاف ─────────────────────────────────────


def test_blocked_attempts_do_not_extend_the_pause():
    rl = RateLimiter(max_hits=2, window_seconds=60)
    rl.hit("ip", now=0.0)
    rl.hit("ip", now=1.0)
    for t in (2.0, 10.0, 30.0, 59.0):  # ضغط متكرر أثناء الإيقاف
        with pytest.raises(RateLimitedError):
            rl.hit("ip", now=t)
    rl.hit("ip", now=60.5)  # خرجت المحاولة الأولى من النافذة ⇒ مسموح فوراً، لا تأخير بسبب المرفوضات


def test_retry_after_counts_down_to_the_oldest_hit_leaving_the_window():
    rl = RateLimiter(max_hits=1, window_seconds=300)
    rl.hit("ip", now=1000.0)
    with pytest.raises(RateLimitedError) as exc:
        rl.hit("ip", now=1100.0)
    assert exc.value.retry_after_seconds == 200
    assert "3 دقائق و20 ثانية" in str(exc.value)


# ── عبر HTTP ────────────────────────────────────────────────────────────────


def test_wrong_password_reports_attempts_left_counting_down(client):
    limit = settings.login_rate_limit_max
    for n in range(1, limit):
        r = client.post("/auth/login", json={"username": "qa_nobody", "password": "x"})
        assert r.status_code == 401
        assert r.json()["detail"] == (
            "اسم المستخدم أو كلمة المرور غير صحيحة — " + format_attempts_left_ar(limit - n)
        )


def test_unknown_and_known_usernames_get_the_same_count(db, client):
    """الرقم من عدّاد العنوان وحده — لا يكشف وجود الاسم."""
    user = _user_with_totp(db)
    known = client.post("/auth/login", json={"username": user.username, "password": "wrong"}).json()["detail"]
    deps._login_rate_limiter.reset()
    unknown = client.post("/auth/login", json={"username": "qa_nobody", "password": "wrong"}).json()["detail"]
    assert known == unknown


def test_wrong_totp_code_reports_attempts_left(db, client):
    user = _user_with_totp(db)
    good = pyotp.TOTP(user.totp_secret).now()
    bad = "000000" if good != "000000" else "111111"
    r = client.post("/auth/login", json={"username": user.username, "password": PASSWORD, "totp_code": bad})
    assert r.status_code == 401
    # طلب واحد استُهلك من النافذة
    assert r.json()["detail"] == "رمز التحقق غير صحيح — " + format_attempts_left_ar(settings.login_rate_limit_max - 1)


def test_rate_limited_response_has_minutes_seconds_and_retry_after(client):
    for _ in range(settings.login_rate_limit_max):
        client.post("/auth/login", json={"username": "qa_nobody", "password": "x"})
    r = client.post("/auth/login", json={"username": "qa_nobody", "password": "x"})
    assert r.status_code == 429
    wait = int(r.headers["Retry-After"])
    assert 0 < wait <= settings.login_rate_limit_window_seconds
    assert r.json()["detail"] == f"طلبات كثيرة — حاول بعد {format_wait_ar(wait)}"
    assert str(wait) not in r.json()["detail"] or wait < 60  # لا رقم ثوانٍ خام يتجاوز الدقيقة


def test_pause_does_not_grow_when_the_user_keeps_retrying(client, monkeypatch):
    base = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(deps, "system_clock", lambda: base)
    for _ in range(settings.login_rate_limit_max):
        client.post("/auth/login", json={"username": "qa_x", "password": "x"})
    first = client.post("/auth/login", json={"username": "qa_x", "password": "x"})
    assert first.status_code == 429
    for _ in range(20):
        client.post("/auth/login", json={"username": "qa_x", "password": "x"})
    monkeypatch.setattr(deps, "system_clock", lambda: base + timedelta(seconds=settings.login_rate_limit_window_seconds + 1))
    assert client.post("/auth/login", json={"username": "qa_x", "password": "x"}).status_code == 401


def test_locked_account_returns_countdown_and_retry_after(db, client):
    user = _user_with_totp(db)
    user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=14, seconds=30)
    db.flush()
    r = client.post("/auth/login", json={"username": user.username, "password": PASSWORD})
    assert r.status_code == 423
    wait = int(r.headers["Retry-After"])
    assert 14 * 60 <= wait <= 14 * 60 + 31
    assert r.json()["detail"] == f"الحساب مقفل مؤقتاً بعد محاولات فاشلة — حاول بعد {format_wait_ar(wait)}"
    assert "دقيقة" in r.json()["detail"]


def test_production_defaults_are_eight_attempts_in_five_minutes():
    from app.config import PRODUCTION_MAX_LOGIN_RATE_LIMIT, PRODUCTION_MIN_RATE_LIMIT_WINDOW_SECONDS
    from app.security import lockout

    assert (PRODUCTION_MAX_LOGIN_RATE_LIMIT, PRODUCTION_MIN_RATE_LIMIT_WINDOW_SECONDS) == (8, 300)
    # الرقم المعروض مصدره عدّاد العنوان؛ قفل الحساب لا يسبقه
    assert lockout.MAX_FAILED_ATTEMPTS == PRODUCTION_MAX_LOGIN_RATE_LIMIT
