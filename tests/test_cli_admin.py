"""اختبارات أوامر CLI التفاعلية لإنشاء أول مدير وإعادة تعيين كلمة مروره —
`input`/`getpass.getpass` مُصطنَعان (mocked)، الاتصال الفعلي بقاعدة
البيانات حقيقي عبر `app.database.SessionLocal` (لا عزل `db` fixture هنا
عمداً — هذه الأوامر تُصمَّم للعمل خارج أي معاملة اختبار، وتلتزم فعلياً)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.security import passwords
from tests.factories import uid


@pytest.fixture()
def cleanup_users():
    created_usernames: list[str] = []
    yield created_usernames
    db = SessionLocal()
    try:
        for username in created_usernames:
            db.execute(select(User).where(User.username == username))
            row = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
            if row is not None:
                db.delete(row)
        db.commit()
    finally:
        db.close()


def test_create_admin_interactive(cleanup_users):
    from app.cli.create_admin import run

    username = f"test-admin-{uid()}"
    cleanup_users.append(username)

    inputs = iter([username, "مدير الاختبار", "", ""])  # اسم مستخدم، اسم كامل، لا سؤال تحقق
    passwords_iter = iter(["Sup3rSecret!1", "Sup3rSecret!1"])  # كلمة المرور + تأكيدها

    with patch("builtins.input", lambda _prompt="": next(inputs)), \
         patch("getpass.getpass", lambda _prompt="": next(passwords_iter)):
        run()

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.username == username)).scalar_one()
        assert user.role == "ADMIN"
        assert user.must_change_password is True
        assert passwords.verify_password("Sup3rSecret!1", user.password_hash)
    finally:
        db.close()


def test_reset_admin_password_clears_totp_and_forces_change(cleanup_users):
    from app.cli.create_admin import run as create_admin
    from app.cli.reset_admin_password import run as reset_password

    username = f"test-admin-{uid()}"
    cleanup_users.append(username)

    inputs = iter([username, "مدير الاختبار", "", ""])
    pw_inputs = iter(["Sup3rSecret!1", "Sup3rSecret!1"])
    with patch("builtins.input", lambda _prompt="": next(inputs)), \
         patch("getpass.getpass", lambda _prompt="": next(pw_inputs)):
        create_admin()

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.username == username)).scalar_one()
        user.totp_secret = "SOMESECRETVALUEXXXXXXXXXXXXXXXX"
        user.must_change_password = False
        db.commit()
    finally:
        db.close()

    reset_inputs = iter([username])
    reset_pw_inputs = iter(["BrandNewPass!2", "BrandNewPass!2"])
    with patch("builtins.input", lambda _prompt="": next(reset_inputs)), \
         patch("getpass.getpass", lambda _prompt="": next(reset_pw_inputs)):
        reset_password()

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.username == username)).scalar_one()
        assert user.totp_secret is None
        assert user.must_change_password is True
        assert passwords.verify_password("BrandNewPass!2", user.password_hash)
    finally:
        db.close()
