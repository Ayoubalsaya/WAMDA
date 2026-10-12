"""`python -m app.cli unlock-user` (٢٠٢٦-١٠-١٢): يفك القفل فقط، لا يمسّ كلمة المرور ولا 2FA، ويُدقَّق."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from sqlalchemy import select

from app.cli.unlock_user import unlock_user
from app.models import AuditLog
from app.security.passwords import hash_password
from tests import factories as f


def test_unlock_clears_lock_only_and_audits(db):
    user = f.make_user(db, role="ADMIN")
    user.password_hash = hash_password("Sup3rSecret!1")
    user.totp_secret = pyotp.random_base32()
    user.failed_attempts = 3
    user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.flush()
    pw, secret = user.password_hash, user.totp_secret

    unlock_user(db, username=user.username)
    db.refresh(user)

    assert user.failed_attempts == 0 and user.locked_until is None
    assert user.password_hash == pw and user.totp_secret == secret
    row = db.execute(
        select(AuditLog).where(AuditLog.action == "ACCOUNT_UNLOCKED", AuditLog.entity_id == user.id)
    ).scalar_one()
    assert row.after_json["via"] == "cli" and row.before_json == {"failed_attempts": 3, "locked": True}


def test_unlock_unknown_user_raises(db):
    with pytest.raises(ValueError):
        unlock_user(db, username="no_such_user_" + f.uid())
