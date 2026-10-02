"""`reset-admin-password` مساوٍ لـ`reset-2fa` (٢٠٢٦-١٠-٠٣): ينهي الجلسات · يُدقَّق · يطلب تأكيداً كتابياً."""

from __future__ import annotations

from datetime import datetime, timezone

import pyotp
import pytest
from sqlalchemy import select

from app.cli import reset_admin_password as cli
from app.models import AuditLog
from app.models.enums import SessionSubjectType
from app.security import passwords, sessions
from tests import factories as f


def _admin(db):
    user = f.make_user(db, role="ADMIN")
    user.password_hash = passwords.hash_password("OldPassword!123")
    user.totp_secret = pyotp.random_base32()
    user.must_change_password = False
    user.failed_attempts = 5
    db.flush()
    return user


def test_reset_password_revokes_sessions_clears_totp_and_audits_without_the_secret(db):
    user = _admin(db)
    now = datetime.now(timezone.utc)
    _row, token = sessions.create_session(db, subject_type=SessionSubjectType.USER, subject_id=user.id, now=now, ip="1.1.1.1", ua="t")
    assert sessions.get_valid_session(db, token, now) is not None

    cli.reset_password(db, username=user.username, new_password="BrandNewPass!456")
    db.refresh(user)
    assert sessions.get_valid_session(db, token, now) is None, "الجلسة القديمة يجب أن تُنهى"
    assert passwords.verify_password("BrandNewPass!456", user.password_hash)
    assert user.must_change_password is True and user.totp_secret is None and user.failed_attempts == 0
    row = db.execute(select(AuditLog).where(AuditLog.action == "ADMIN_PASSWORD_RESET", AuditLog.entity_id == user.id)).scalar_one()
    assert row.after_json["via"] == "cli" and row.after_json["sessions_revoked"] >= 1
    dumped = f"{row.before_json}{row.after_json}"
    assert "BrandNewPass" not in dumped and user.password_hash not in dumped


def test_reset_password_rejects_unknown_admin_non_admin_and_short_password(db):
    admin = _admin(db)
    with pytest.raises(ValueError):
        cli.reset_password(db, username="no_such_" + f.uid(), new_password="LongEnoughPass!1")
    accountant = f.make_user(db, role="ACCOUNTANT")
    with pytest.raises(ValueError):
        cli.reset_password(db, username=accountant.username, new_password="LongEnoughPass!1")
    with pytest.raises(ValueError):
        cli.reset_password(db, username=admin.username, new_password="short")


class _Session:
    """يلفّ جلسة الاختبار: `close` لا يغلقها و`commit` = flush (العزل يبقى)."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass

    def commit(self):
        self._db.flush()


def _drive(monkeypatch, db, *, username, confirmation, password="NewSecurePass!789"):
    monkeypatch.setattr(cli, "SessionLocal", lambda: _Session(db))
    answers = iter([username, confirmation])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": password)


def test_cli_requires_typed_username_confirmation(db, monkeypatch):
    user = _admin(db)
    old_hash = user.password_hash
    _drive(monkeypatch, db, username=user.username, confirmation="خطأ")
    with pytest.raises(SystemExit) as exc:
        cli.run()
    assert exc.value.code == 1
    db.refresh(user)
    assert user.password_hash == old_hash and user.totp_secret is not None, "لا تغيير بلا تأكيد صحيح"
    assert db.execute(select(AuditLog).where(AuditLog.action == "ADMIN_PASSWORD_RESET", AuditLog.entity_id == user.id)).first() is None


def test_cli_with_correct_confirmation_applies_the_reset(db, monkeypatch):
    user = _admin(db)
    _drive(monkeypatch, db, username=user.username, confirmation=user.username)
    cli.run()
    db.refresh(user)
    assert passwords.verify_password("NewSecurePass!789", user.password_hash) and user.totp_secret is None
