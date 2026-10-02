"""`python -m app.cli reset-2fa` (٢٠٢٦-١٠-٠٢، فقدان جهاز المصادقة): يمسح totp_secret فقط، يُنهي الجلسات، يُدقَّق."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from sqlalchemy import select

from app.cli.reset_2fa import reset_totp
from app.models import AuditLog
from app.models.enums import SessionSubjectType
from app.security import sessions
from app.security.passwords import hash_password
from tests import factories as f


def _user_with_totp(db):
    user = f.make_user(db, role="ADMIN")
    user.password_hash = hash_password("Sup3rSecret!1")
    user.totp_secret = pyotp.random_base32()
    user.failed_attempts = 4
    user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.flush()
    return user


def test_reset_clears_only_totp_revokes_sessions_and_audits(db):
    user = _user_with_totp(db)
    password_hash = user.password_hash
    now = datetime.now(timezone.utc)
    _row, raw_token = sessions.create_session(
        db, subject_type=SessionSubjectType.USER, subject_id=user.id, now=now, ip="127.0.0.1", ua="t")
    assert sessions.get_valid_session(db, raw_token, now) is not None
    reset_totp(db, username=user.username)
    db.refresh(user)
    assert user.totp_secret is None
    assert sessions.get_valid_session(db, raw_token, now) is None, "الجلسة القائمة يجب أن تُنهى"
    assert user.password_hash == password_hash, "كلمة المرور يجب ألا تُمسّ"
    assert user.failed_attempts == 0 and user.locked_until is None
    row = db.execute(select(AuditLog).where(AuditLog.action == "TOTP_RESET", AuditLog.entity_id == user.id)).scalar_one()
    assert row.after_json["via"] == "cli" and row.before_json["had_totp"] is True


def test_reset_unknown_user_raises(db):
    with pytest.raises(ValueError):
        reset_totp(db, username="no_such_user_" + f.uid())


def test_login_after_reset_requires_new_totp_setup(db):
    """بعد الإعادة: الدخول بكلمة المرور يطلب تسجيل جهاز جديد (QR) لا رمزاً قديماً."""
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app

    user = _user_with_totp(db)
    user.must_change_password = False
    reset_totp(db, username=user.username)
    db.flush()

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app, base_url="https://testserver") as c:
            resp = c.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1"})
            assert resp.status_code == 200 and resp.json()["status"] == "totp_setup_required"
    finally:
        app.dependency_overrides.clear()
