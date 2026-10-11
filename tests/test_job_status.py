"""فشل مهمة مجدولة يظهر في لوحة التحكم ويزول بأول نجاح لاحق (٢٠٢٦-١٠-١٢): قناة التنبيه الوحيدة إلى أن يُعدّ البريد."""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.cli import job_status
from app.database import get_db
from app.main import app
from app.security.passwords import hash_password
from tests import factories as f


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


def _login(db, client):
    user = f.make_user(db, role="ADMIN")
    user.password_hash = hash_password("Sup3rSecret!1")
    user.must_change_password = False
    user.totp_secret = pyotp.random_base32()
    db.flush()
    code = pyotp.TOTP(user.totp_secret).now()
    resp = client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": code})
    assert resp.status_code == 200, resp.text


def _codes(client):
    return [a["code"] for a in client.get("/dashboard/summary").json()["alerts"]]


def test_failed_job_raises_critical_alert_then_clears_on_success(db, client):
    _login(db, client)
    assert not any(c.startswith("job_failed_") for c in _codes(client))

    job_status.record("backup", ok=False, db=db)
    alerts = client.get("/dashboard/summary").json()["alerts"]
    row = next(a for a in alerts if a["code"] == "job_failed_backup")
    assert row["severity"] == "critical"
    assert "النسخ الاحتياطي" in row["message_ar"] and "wamda-backup" in row["message_ar"]

    job_status.record("backup", ok=True, db=db)
    assert "job_failed_backup" not in _codes(client)


def test_each_job_has_its_own_alert_and_unknown_job_is_refused(db, client):
    _login(db, client)
    for job in ("integrity", "backup-fresh", "restore-test"):
        job_status.record(job, ok=False, db=db)
    codes = _codes(client)
    assert {"job_failed_integrity", "job_failed_backup-fresh", "job_failed_restore-test"} <= set(codes)
    assert "job_failed_backup" not in codes
    with pytest.raises(ValueError):
        job_status.record("rm-rf", ok=False, db=db)


def test_cli_job_status_parser_accepts_only_known_jobs_and_one_flag():
    import subprocess
    import sys

    base = [sys.executable, "-W", "ignore", "-m", "app.cli", "job-status"]
    bad_job = subprocess.run(base + ["nope", "--failed"], capture_output=True, text=True)
    both = subprocess.run(base + ["backup", "--failed", "--ok"], capture_output=True, text=True)
    neither = subprocess.run(base + ["backup"], capture_output=True, text=True)
    assert bad_job.returncode == 2 and both.returncode == 2 and neither.returncode == 2


def test_restore_test_latest_resolves_newest_local_backup(tmp_path, monkeypatch):
    import os
    import time

    from app.cli import restore as restore_cli
    from app.config import settings

    monkeypatch.setattr(settings, "backup_dir", str(tmp_path))
    assert restore_cli.latest_local_backup() is None
    old = tmp_path / "wamda-20260101T000000Z.dump.enc"
    new = tmp_path / "wamda-20260102T000000Z.dump.enc"
    other = tmp_path / "notes.txt"
    for p in (old, new, other):
        p.write_bytes(b"x")
    os.utime(old, (time.time() - 100, time.time() - 100))
    assert restore_cli.latest_local_backup() == new


def test_backup_dir_setting_controls_destination(monkeypatch, tmp_path):
    """الخدمة تعمل من مجلد الكود: بلا BACKUP_DIR تذهب النسخ إلى <الكود>/backups لا /srv/wamda/backups."""
    from app.cli import backup as backup_cli
    from app.config import settings

    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "bk"))
    monkeypatch.setattr(settings, "backup_encryption_key", None)  # يفشل مبكراً قبل أي pg_dump
    with pytest.raises(backup_cli.BackupError):
        backup_cli.run()
    # الإعداد مقروء فعلاً من الإعدادات لا ثابت "backups"
    import inspect
    assert "settings.backup_dir" in inspect.getsource(backup_cli.run)
