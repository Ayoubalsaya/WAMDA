"""مهلة الخمول (٢٠٢٦-١٠-٠٦): الموظف ٣٠ دقيقة، البوابة ١٥ — فوق السقف المطلق ٨ ساعات."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyotp
from sqlalchemy import select

from app.models import Session as SessionRow
from app.models.enums import SessionSubjectType
from app.security import sessions
from app.security.passwords import hash_password
from tests import factories as f
from tests.test_session_invalidation import db_client  # noqa: F401  (fixture)


def _login(db, client):
    user = f.make_user(db, role="ADMIN")
    user.password_hash = hash_password("Sup3rSecret!1")
    user.totp_secret = pyotp.random_base32()
    db.flush()
    code = pyotp.TOTP(user.totp_secret).now()
    r = client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": code})
    assert r.status_code == 200
    return db.execute(select(SessionRow).where(SessionRow.subject_id == user.id)).scalar_one()


def test_defaults_are_30_staff_15_portal():
    assert sessions.idle_timeout_for(SessionSubjectType.USER) == timedelta(minutes=30)
    assert sessions.idle_timeout_for(SessionSubjectType.CLIENT) == timedelta(minutes=15)


def test_staff_session_valid_just_before_and_dead_just_after_idle_limit(db, now):
    row, raw = sessions.create_session(db, subject_type=SessionSubjectType.USER, subject_id=1, now=now)
    assert sessions.get_valid_session(db, raw, now + timedelta(minutes=29, seconds=59)) is not None
    assert sessions.get_valid_session(db, raw, now + timedelta(minutes=30)) is None


def test_portal_session_dies_after_15_minutes(db, now):
    row, raw = sessions.create_session(db, subject_type=SessionSubjectType.CLIENT, subject_id=1, now=now)
    assert sessions.get_valid_session(db, raw, now + timedelta(minutes=14)) is not None
    assert sessions.get_valid_session(db, raw, now + timedelta(minutes=15)) is None


def test_touch_is_throttled_and_extends_the_window(db, now):
    row, raw = sessions.create_session(db, subject_type=SessionSubjectType.USER, subject_id=1, now=now)
    assert sessions.touch(db, row, now + timedelta(seconds=30)) is False  # أقل من دقيقة — لا كتابة
    assert sessions.touch(db, row, now + timedelta(minutes=20)) is True
    assert sessions.get_valid_session(db, raw, now + timedelta(minutes=45)) is not None  # ٢٥ د من آخر نشاط
    assert sessions.get_valid_session(db, raw, now + timedelta(minutes=51)) is None


def test_absolute_ceiling_still_applies_despite_activity(db, now):
    row, raw = sessions.create_session(db, subject_type=SessionSubjectType.USER, subject_id=1, now=now)
    row.last_seen_at = now + timedelta(hours=7, minutes=59)
    assert sessions.get_valid_session(db, raw, now + timedelta(hours=8)) is None


def test_http_idle_staff_session_gets_401_and_activity_keeps_it_alive(db, db_client):  # noqa: F811
    c = db_client()
    row = _login(db, c)
    assert c.get("/auth/me").status_code == 200
    row.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=29)  # قرب الحدّ
    db.flush()
    assert c.get("/auth/me").status_code == 200  # نشاط فعلي → يجدّد
    db.refresh(row)
    assert datetime.now(timezone.utc) - row.last_seen_at < timedelta(minutes=1)
    row.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    db.flush()
    assert c.get("/auth/me").status_code == 401


def test_background_poll_does_not_keep_session_alive(db, db_client):  # noqa: F811
    c = db_client()
    row = _login(db, c)
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    row.last_seen_at = stale
    db.flush()
    assert c.get("/auth/me", headers={"X-Wamda-Background": "1"}).status_code == 200
    db.refresh(row)
    assert row.last_seen_at == stale  # لم يُجدَّد
    assert c.get("/auth/me").status_code == 200
    db.refresh(row)
    assert row.last_seen_at > stale
