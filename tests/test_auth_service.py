"""اختبارات app.security.auth_service — تدفّق الدخول بخطوتين، التسجيل
الأول لـTOTP، تغيير كلمة المرور."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyotp
import pytest

from app.security import auth_service, passwords, sessions
from app.security.passwords import hash_password
from tests import factories as f

NOW = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)


def _make_staff_user(db, *, role="ADMIN", password="Sup3rSecret!1", with_totp=False, must_change_password=True):
    user = f.make_user(db, role=role)
    user.password_hash = hash_password(password)
    # المصنع المشترك (tests/factories.py) يضبطها False لراحة اختبارات
    # المرحلة ٣ — هنا نختبر المصادقة نفسها فنعيدها للافتراضي الحقيقي (§٧-١).
    user.must_change_password = must_change_password
    if with_totp:
        user.totp_secret = pyotp.random_base32()
    db.flush()
    return user


def test_login_step1_wrong_password_records_failed_attempt(db):
    user = _make_staff_user(db)
    with pytest.raises(auth_service.InvalidCredentialsError):
        auth_service.login_step1(db, username=user.username, password="wrong", now=NOW)
    assert user.failed_attempts == 1


def test_login_step1_unknown_username_rejected(db):
    with pytest.raises(auth_service.InvalidCredentialsError):
        auth_service.login_step1(db, username="لا-يوجد-مستخدم-بهذا-الاسم", password="x", now=NOW)


def test_login_step1_locked_account_rejected(db):
    from app.security import lockout

    user = _make_staff_user(db)
    for _ in range(lockout.MAX_FAILED_ATTEMPTS):
        lockout.record_failed_attempt(db, user, NOW)
    with pytest.raises(lockout.AccountLockedError):
        auth_service.login_step1(db, username=user.username, password="Sup3rSecret!1", now=NOW)


def test_first_login_requires_totp_setup(db):
    user = _make_staff_user(db, with_totp=False)
    # login_step1 لا يقرر بشأن TOTP إطلاقاً — كلمة المرور وحدها تكفي لنجاحه
    verified_user = auth_service.login_step1(db, username=user.username, password="Sup3rSecret!1", now=NOW)
    assert verified_user.totp_secret is None  # القرار متروك للمستدعي (الموجّه)

    challenge = auth_service.generate_totp_setup_challenge(verified_user)
    assert challenge.candidate_secret
    assert user.username in challenge.provisioning_uri


def test_totp_setup_persists_secret_only_after_correct_code(db):
    user = _make_staff_user(db, with_totp=False)
    auth_service.login_step1(db, username=user.username, password="Sup3rSecret!1", now=NOW)
    challenge = auth_service.generate_totp_setup_challenge(user)
    candidate = challenge.candidate_secret

    # كود خاطئ لا يُثبِّت السر ولا ينشئ جلسة
    with pytest.raises(auth_service.InvalidTwoFactorCodeError):
        auth_service.login_step2_setup(db, user=user, candidate_secret=candidate, totp_code="000000", now=NOW)
    assert user.totp_secret is None

    valid_code = pyotp.TOTP(candidate).now()
    result = auth_service.login_step2_setup(
        db, user=user, candidate_secret=candidate, totp_code=valid_code, now=NOW
    )
    assert user.totp_secret == candidate
    assert result.must_change_password is True  # افتراضي عند الإنشاء
    assert result.raw_token


def test_normal_login_with_existing_totp(db):
    user = _make_staff_user(db, with_totp=True)
    valid_code = pyotp.TOTP(user.totp_secret).now()
    verified_user = auth_service.login_step1(db, username=user.username, password="Sup3rSecret!1", now=NOW)
    result = auth_service.login_step2_verify(db, user=verified_user, totp_code=valid_code, now=NOW)
    assert result.raw_token
    session_row = sessions.get_valid_session(db, result.raw_token, NOW)
    assert session_row is not None
    assert session_row.expires_at == NOW + sessions.SESSION_TTL


def test_wrong_totp_code_records_failed_attempt_no_session(db):
    user = _make_staff_user(db, with_totp=True)
    with pytest.raises(auth_service.InvalidTwoFactorCodeError):
        auth_service.login_step2_verify(db, user=user, totp_code="000000", now=NOW)
    assert user.failed_attempts == 1


def test_change_password_revokes_other_sessions_keeps_current(db):
    user = _make_staff_user(db, with_totp=True)
    valid_code = pyotp.TOTP(user.totp_secret).now()
    result1 = auth_service.login_step2_verify(db, user=user, totp_code=valid_code, now=NOW)
    result2 = auth_service.login_step2_verify(
        db, user=user, totp_code=pyotp.TOTP(user.totp_secret).now(), now=NOW + timedelta(seconds=1)
    )

    auth_service.change_password(
        db, user=user, new_password="NewSecret!2", now=NOW, keep_session_id=str(result2.session.id)
    )

    assert sessions.get_valid_session(db, result1.raw_token, NOW) is None  # أُبطلت
    assert sessions.get_valid_session(db, result2.raw_token, NOW) is not None  # أُبقيت
    assert passwords.verify_password("NewSecret!2", user.password_hash)
    assert user.must_change_password is False
