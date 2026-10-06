"""تشفير `users.totp_secret` (Fernet، مفتاح مستقل `TOTP_ENCRYPTION_KEY`) — ٢٠٢٦-١٠-٠٦."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pyotp
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import text

from app.config import Settings, settings
from app.models import User
from app.models import crypto_types
from tests import factories as f

_DB_URL = "postgresql+psycopg://wamda_app:x@localhost:5432/wamda_db"
_MIGRATION = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "d2e4f6a8b0c1_encrypt_totp_secret.py"


def _raw_secret(db, user_id: int):
    return db.execute(text("SELECT totp_secret FROM users WHERE id = :i"), {"i": user_id}).scalar()


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_encrypt_totp", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_secret_is_stored_encrypted_and_read_back_in_clear(db):
    user = f.make_user(db)
    secret = pyotp.random_base32()
    user.totp_secret = secret
    db.flush()
    raw = _raw_secret(db, user.id)
    assert raw.startswith(crypto_types.PREFIX)
    assert secret not in raw
    db.expire_all()
    assert db.get(User, user.id).totp_secret == secret  # يُفكّ شفافاً → TOTP يعمل
    assert pyotp.TOTP(db.get(User, user.id).totp_secret).verify(pyotp.TOTP(secret).now())


def test_none_stays_none(db):
    user = f.make_user(db)
    assert user.totp_secret is None
    assert _raw_secret(db, user.id) is None


def test_encryption_is_not_deterministic(db):
    a, b = f.make_user(db), f.make_user(db)
    a.totp_secret = b.totp_secret = "JBSWY3DPEHPK3PXP"
    db.flush()
    assert _raw_secret(db, a.id) != _raw_secret(db, b.id)


def test_wrong_key_fails_loudly_not_silently(db, monkeypatch):
    user = f.make_user(db)
    user.totp_secret = "JBSWY3DPEHPK3PXP"
    db.flush()
    monkeypatch.setattr(settings, "totp_encryption_key", Fernet.generate_key().decode())
    db.expire_all()
    with pytest.raises(RuntimeError, match="لا يطابق"):
        _ = db.get(User, user.id).totp_secret


def test_production_refuses_plaintext_rows(db, monkeypatch):
    user = f.make_user(db)
    db.execute(text("UPDATE users SET totp_secret = 'JBSWY3DPEHPK3PXP' WHERE id = :i"), {"i": user.id})
    monkeypatch.setattr(settings, "app_env", "production")
    db.expire_all()
    with pytest.raises(RuntimeError, match="alembic upgrade"):
        _ = db.get(User, user.id).totp_secret


def test_migration_encrypts_existing_plaintext_and_is_idempotent(db):
    user = f.make_user(db)
    other = f.make_user(db)
    db.execute(text("UPDATE users SET totp_secret = 'JBSWY3DPEHPK3PXP' WHERE id = :i"), {"i": user.id})
    mig = _load_migration()
    conn = db.connection()
    with Operations.context(MigrationContext.configure(conn)):
        mig.upgrade()
        first = _raw_secret(db, user.id)
        mig.upgrade()  # مرتين بلا ضرر
        assert _raw_secret(db, user.id) == first
        assert first.startswith("enc1:") and "JBSWY3DPEHPK3PXP" not in first
        assert _raw_secret(db, other.id) is None
        mig.downgrade()
        assert _raw_secret(db, user.id) == "JBSWY3DPEHPK3PXP"


def test_migration_without_key_stops_with_clear_error_and_changes_nothing(db, monkeypatch):
    user = f.make_user(db)
    db.execute(text("UPDATE users SET totp_secret = 'JBSWY3DPEHPK3PXP' WHERE id = :i"), {"i": user.id})
    monkeypatch.setattr(settings, "totp_encryption_key", None)
    mig = _load_migration()
    with Operations.context(MigrationContext.configure(db.connection())):
        with pytest.raises(RuntimeError, match="TOTP_ENCRYPTION_KEY"):
            mig.upgrade()
    assert _raw_secret(db, user.id) == "JBSWY3DPEHPK3PXP"


def test_production_refuses_to_boot_without_the_key():
    with pytest.raises(ValidationError) as exc:
        Settings(database_url=_DB_URL, app_env="production", totp_encryption_key=None, _env_file=None)
    assert "TOTP_ENCRYPTION_KEY" in str(exc.value)


def test_invalid_key_refuses_to_boot_anywhere():
    with pytest.raises(ValidationError) as exc:
        Settings(database_url=_DB_URL, app_env="local", totp_encryption_key="not-a-fernet-key", _env_file=None)
    assert "Fernet" in str(exc.value)


def test_local_without_key_is_allowed():
    s = Settings(database_url=_DB_URL, app_env="local", totp_encryption_key=None, _env_file=None)
    assert s.totp_encryption_key is None
