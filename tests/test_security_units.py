"""اختبارات وحدة للمصادقة نفسها: كلمات المرور · TOTP · الرموز · CSRF ·
القفل بعد ٥ محاولات · مصفوفة الصلاحيات بندًا بندًا (§٧-١٣)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyotp
import pytest

from app.security import csrf, lockout, passwords, tokens, totp
from app.security.permissions import PERMISSION_MATRIX, ACCOUNTANT, ADMIN, CLIENT_ROLE, Action, has_permission
from tests import factories as f

NOW = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)


# ── كلمات المرور ────────────────────────────────────────────────────────
def test_password_hash_roundtrip():
    hashed = passwords.hash_password("Sup3rSecret!")
    assert passwords.verify_password("Sup3rSecret!", hashed) is True
    assert passwords.verify_password("wrong", hashed) is False
    assert hashed != "Sup3rSecret!"  # لا نص صريح مخزَّن


def test_security_answer_normalized():
    hashed = passwords.hash_security_answer("  Tripoli  ")
    assert passwords.verify_security_answer("tripoli", hashed) is True
    assert passwords.verify_security_answer("TRIPOLI", hashed) is True
    assert passwords.verify_security_answer("benghazi", hashed) is False


# ── TOTP ─────────────────────────────────────────────────────────────────
def test_totp_verify_correct_and_incorrect_code():
    secret = totp.generate_totp_secret()
    valid_code = pyotp.TOTP(secret).now()
    assert totp.verify_totp_code(secret, valid_code) is True
    assert totp.verify_totp_code(secret, "000000") is False
    assert totp.verify_totp_code(None, valid_code) is False


# ── الرموز ───────────────────────────────────────────────────────────────
def test_session_token_roundtrip():
    raw, hashed = tokens.generate_session_token()
    assert tokens.hash_token(raw) == hashed
    assert raw != hashed


def test_constant_time_equal():
    assert tokens.constant_time_equal("abc", "abc") is True
    assert tokens.constant_time_equal("abc", "abd") is False
    assert tokens.constant_time_equal(None, "abc") is False


# ── CSRF ─────────────────────────────────────────────────────────────────
def test_csrf_verify():
    token = csrf.generate_csrf_token()
    assert csrf.verify_csrf_token(token, token) is True
    assert csrf.verify_csrf_token(token, "different") is False
    assert csrf.verify_csrf_token(None, token) is False
    assert csrf.verify_csrf_token(token, None) is False


# ── القفل بعد ٥ محاولات فاشلة، ١٥ دقيقة ─────────────────────────────────
def test_lockout_after_five_failed_attempts(db):
    user = f.make_user(db)
    for _ in range(4):
        lockout.record_failed_attempt(db, user, NOW)
        lockout.check_not_locked(user, NOW)  # لم يُقفل بعد

    lockout.record_failed_attempt(db, user, NOW)  # المحاولة الخامسة
    assert user.locked_until == NOW + timedelta(minutes=15)
    assert user.failed_attempts == 0  # يُصفَّر عند القفل نفسه

    with pytest.raises(lockout.AccountLockedError):
        lockout.check_not_locked(user, NOW)

    # لا يزال مقفلاً قبل انتهاء الخمس عشرة دقيقة بلحظة واحدة
    with pytest.raises(lockout.AccountLockedError):
        lockout.check_not_locked(user, NOW + timedelta(minutes=15) - timedelta(seconds=1))

    # ينفتح تلقائياً بعد انتهاء المهلة — لا حاجة لأي إجراء يدوي
    lockout.check_not_locked(user, NOW + timedelta(minutes=15, seconds=1))


def test_reset_failed_attempts_clears_lock(db):
    user = f.make_user(db)
    for _ in range(5):
        lockout.record_failed_attempt(db, user, NOW)
    assert user.locked_until is not None

    lockout.reset_failed_attempts(db, user)
    assert user.failed_attempts == 0
    assert user.locked_until is None
    lockout.check_not_locked(user, NOW)  # لا يرفع شيئاً الآن


# ── مصفوفة الصلاحيات بندًا بندًا (§٧-١٣) ─────────────────────────────────
@pytest.mark.parametrize(
    "action,admin_allowed,accountant_allowed,client_allowed",
    [
        (Action.POST_ENTRY, True, True, False),
        (Action.EDIT_POSTED_ENTRY, True, False, False),
        (Action.BACKDATED_OR_OUTAGE_ENTRY, True, False, False),
        (Action.REOPEN_CLOSED_PERIOD, True, False, False),
        (Action.OVERRIDE_CREDIT_OR_BALANCE, True, False, False),
        (Action.RECONCILIATION, True, False, False),
        (Action.OPENING_BALANCES, True, False, False),
        (Action.VIEW_OWN_STATEMENT, False, False, True),
        (Action.CLOSE_PERIOD, True, False, False),
        (Action.VIEW_AUDIT_LOG, True, False, False),
    ],
)
def test_permission_matrix_cell(action, admin_allowed, accountant_allowed, client_allowed):
    assert has_permission(ADMIN, action) is admin_allowed
    assert has_permission(ACCOUNTANT, action) is accountant_allowed
    assert has_permission(CLIENT_ROLE, action) is client_allowed


def test_permission_matrix_covers_every_action_defined():
    for action in Action:
        assert action in PERMISSION_MATRIX, f"لا تعريف صلاحية لـ {action}"
