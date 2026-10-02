"""رموز المصادقة الاحتياطية (٢٠٢٦-١٠-٠٣): عشرة رموز لمرة واحدة بدل رمز التطبيق، كلمة المرور مطلوبة دائماً."""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.cli.reset_2fa import reset_totp
from app.database import get_db
from app.main import app
from app.models import AuditLog, User, UserBackupCode
from app.security import backup_codes
from app.security.passwords import hash_password
from tests import factories as f

PASSWORD = "Sup3rSecret!1"


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _user(db, *, role="ADMIN"):
    user = f.make_user(db, role=role)
    user.password_hash = hash_password(PASSWORD)
    user.must_change_password = False
    db.flush()
    return user


def _first_setup(client, user):
    """أول دخول: كلمة المرور ← تحدّي ← إكمال الإعداد برمز التطبيق ← الرموز الاحتياطية في الرد (مرة واحدة)."""
    r1 = client.post("/auth/login", json={"username": user.username, "password": PASSWORD})
    assert r1.json()["status"] == "totp_setup_required"
    secret = r1.json()["totp_secret"]
    r2 = client.post("/auth/login", json={
        "username": user.username, "password": PASSWORD, "totp_secret_setup": secret, "totp_code": pyotp.TOTP(secret).now()})
    assert r2.status_code == 200, r2.text
    return r2.json(), secret


def _backup_login(client, user, code, password=PASSWORD):
    return client.post("/auth/login", json={"username": user.username, "password": password, "backup_code": code})


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("wamda_csrf")}


def _fresh_client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app, base_url="https://testserver")


def test_first_totp_setup_returns_ten_distinct_codes_once(db, client):
    user = _user(db)
    body, _ = _first_setup(client, user)
    codes = body["backup_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    assert all(len(c) == 11 and c[5] == "-" for c in codes)
    assert backup_codes.remaining(db, user_id=user.id) == 10
    # لا تُعرض ثانية: الحالة لا تحمل الرموز
    status = client.get("/auth/backup-codes").json()
    assert status == {"remaining": 10, "total": 10, "low": False}
    assert "codes" not in status


def test_codes_are_stored_hashed_and_never_in_logs(db, client):
    user = _user(db)
    body, _ = _first_setup(client, user)
    codes = body["backup_codes"]
    hashes = db.execute(select(UserBackupCode.code_hash).where(UserBackupCode.user_id == user.id)).scalars().all()
    for c in codes:
        assert c not in hashes and backup_codes.normalize(c) not in hashes
        assert all(backup_codes.normalize(c) not in h for h in hashes)
    # لا أثر للرموز في أي سجل تدقيق (نصاً)
    dump = " ".join(str(r) for r in db.execute(text("SELECT before_json::text, after_json::text, action FROM audit_log")).all())
    for c in codes:
        assert c not in dump and backup_codes.normalize(c) not in dump
    # استعمال رمز ثم فحص التدقيق مجدداً
    _backup_login(client, user, codes[0])
    dump = " ".join(str(r) for r in db.execute(text("SELECT before_json::text, after_json::text FROM audit_log")).all())
    assert codes[0] not in dump and backup_codes.normalize(codes[0]) not in dump


def test_a_code_works_exactly_once(db, client):
    user = _user(db)
    codes = _first_setup(client, user)[0]["backup_codes"]
    client.cookies.clear()
    ok = _backup_login(client, user, codes[0])
    assert ok.status_code == 200 and ok.json()["status"] == "ok" and ok.json()["backup_codes_remaining"] == 9
    client.cookies.clear()
    again = _backup_login(client, user, codes[0])
    assert again.status_code == 401 and "سبق استعماله" in again.json()["detail"]
    # رمز آخر يعمل (كل رمز مستقلّ)، وحالة الكتابة (حروف صغيرة/بلا شرطة) مقبولة
    client.cookies.clear()
    assert _backup_login(client, user, codes[1].lower().replace("-", "")).status_code == 200
    assert backup_codes.remaining(db, user_id=user.id) == 8


def test_unknown_code_is_rejected(db, client):
    user = _user(db)
    _first_setup(client, user)
    client.cookies.clear()
    assert _backup_login(client, user, "AAAAA-AAAAA").status_code == 401
    assert _backup_login(client, user, "قصير").status_code == 401


def test_regenerate_invalidates_every_previous_code(db, client):
    user = _user(db)
    old = _first_setup(client, user)[0]["backup_codes"]
    resp = client.post("/auth/backup-codes/regenerate", json={"password": PASSWORD}, headers=_csrf(client))
    assert resp.status_code == 200, resp.text
    new = resp.json()["codes"]
    assert len(new) == 10 and not set(old) & set(new)
    client.cookies.clear()
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    assert not any(backup_codes.consume(db, user_id=user.id, code=c, now=now) for c in old), "كل رمز قديم يجب أن يُرفض"
    for c in old[:3]:  # وعبر الدخول الفعلي أيضاً (٣ محاولات فقط كي لا يُقفل الحساب بالتجربة)
        assert _backup_login(client, user, c).status_code == 401
    db.refresh(user)
    user.failed_attempts = 0
    db.flush()
    assert _backup_login(client, user, new[0]).status_code == 200
    assert backup_codes.remaining(db, user_id=user.id) == 9


def test_regenerate_requires_the_current_password_and_csrf(db, client):
    user = _user(db)
    _first_setup(client, user)
    bad = client.post("/auth/backup-codes/regenerate", json={"password": "WrongPassword!9"}, headers=_csrf(client))
    assert bad.status_code == 401
    no_csrf = client.post("/auth/backup-codes/regenerate", json={"password": PASSWORD})
    assert no_csrf.status_code in (401, 403)
    assert backup_codes.remaining(db, user_id=user.id) == 10, "المحاولات المرفوضة لا تُبطل الرموز"


def test_no_backup_login_without_the_password(db, client):
    user = _user(db)
    codes = _first_setup(client, user)[0]["backup_codes"]
    client.cookies.clear()
    wrong = _backup_login(client, user, codes[0], password="NotThePassword!1")
    assert wrong.status_code == 401
    assert backup_codes.remaining(db, user_id=user.id) == 10, "الرمز لا يُستهلك عند فشل كلمة المرور"
    missing = client.post("/auth/login", json={"username": user.username, "backup_code": codes[0]})
    assert missing.status_code == 422
    assert client.get("/auth/me").status_code == 401  # لا جلسة


def test_wrong_backup_codes_count_towards_the_same_lockout(db, client):
    user = _user(db)
    codes = _first_setup(client, user)[0]["backup_codes"]
    client.cookies.clear()
    for _ in range(5):
        assert _backup_login(client, user, "ZZZZZ-ZZZZZ").status_code == 401
    db.refresh(user)
    assert user.locked_until is not None
    locked = _backup_login(client, user, codes[0])  # رمز صحيح لكن الحساب مقفل
    assert locked.status_code == 423 and "مقفل" in locked.json()["detail"]
    assert backup_codes.remaining(db, user_id=user.id) == 10


def test_backup_attempts_share_the_ip_login_rate_limit(db, client, monkeypatch):
    from app.security import deps

    user = _user(db)
    _first_setup(client, user)
    client.cookies.clear()
    deps._login_rate_limiter.reset()
    statuses = []
    for _ in range(deps._login_rate_limiter.max_attempts + 3 if hasattr(deps._login_rate_limiter, "max_attempts") else 15):
        statuses.append(client.post("/auth/login", json={"username": "nobody_" + f.uid(), "password": "x", "backup_code": "AAAAA-AAAAA"}).status_code)
    assert 429 in statuses, statuses
    deps._login_rate_limiter.reset()


def test_usage_is_audited_with_remaining_and_shows_in_bell_alerts(db, client):
    admin = _user(db)
    codes = _first_setup(client, admin)[0]["backup_codes"]
    client.cookies.clear()
    _backup_login(client, admin, codes[0])
    row = db.execute(select(AuditLog).where(AuditLog.action == "BACKUP_CODE_LOGIN", AuditLog.entity_id == admin.id)).scalar_one()
    assert row.after_json == {"remaining": 9}
    alerts = client.get("/dashboard/summary").json()["alerts"]
    assert any(a["code"] == "backup_code_login" and a["message_ar"] == "دخول برمز احتياطي — متبقٍّ 9" for a in alerts)

    # مدير آخر يرى الدخول باسم المستخدم؛ محاسب آخر لا يراه
    other_admin = _user(db)
    c2 = _fresh_client(db)
    _first_setup(c2, other_admin)
    msgs = [a["message_ar"] for a in c2.get("/dashboard/summary").json()["alerts"] if a["code"] == "backup_code_login"]
    assert any("متبقٍّ 9" in m and admin.full_name in m for m in msgs)
    accountant = _user(db, role="ACCOUNTANT")
    c3 = _fresh_client(db)
    _first_setup(c3, accountant)
    assert not [a for a in c3.get("/dashboard/summary").json()["alerts"] if a["code"] == "backup_code_login"]


def test_low_remaining_alert_at_three_or_fewer(db, client):
    user = _user(db)
    codes = _first_setup(client, user)[0]["backup_codes"]
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    for c in codes[:6]:  # يبقى ٤
        backup_codes.consume(db, user_id=user.id, code=c, now=now)
    low = lambda: [a for a in client.get("/dashboard/summary").json()["alerts"] if a["code"] == "backup_codes_low"]
    assert low() == []
    backup_codes.consume(db, user_id=user.id, code=codes[6], now=now)  # يبقى ٣
    assert len(low()) == 1 and "3" in low()[0]["message_ar"]
    assert client.get("/auth/backup-codes").json()["low"] is True


def test_reset_2fa_invalidates_codes_and_next_setup_issues_new_ones(db, client):
    user = _user(db)
    old = _first_setup(client, user)[0]["backup_codes"]
    reset_totp(db, username=user.username)
    assert backup_codes.remaining(db, user_id=user.id) == 0
    client.cookies.clear()
    after = _backup_login(client, user, old[0])  # بلا جهاز مصادقة: لا دخول بالرمز، يُطلب إعداد جديد
    assert after.json()["status"] == "totp_setup_required" and client.get("/auth/me").status_code == 401
    body, _ = _first_setup(client, user)
    assert len(body["backup_codes"]) == 10 and not set(old) & set(body["backup_codes"])


def test_consume_is_atomic_for_concurrent_use(db):
    """الاستهلاك `UPDATE … WHERE used_at IS NULL RETURNING`: الاستدعاء الثاني لنفس الرمز يفشل."""
    from datetime import datetime, timezone

    user = _user(db)
    code = backup_codes.generate(db, user_id=user.id, now=datetime.now(timezone.utc))[0]
    now = datetime.now(timezone.utc)
    assert backup_codes.consume(db, user_id=user.id, code=code, now=now) is True
    assert backup_codes.consume(db, user_id=user.id, code=code, now=now) is False
    other = _user(db)
    assert backup_codes.consume(db, user_id=other.id, code=code, now=now) is False, "رمز مستخدم آخر لا يعمل"
