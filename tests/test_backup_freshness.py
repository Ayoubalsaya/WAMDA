"""اختبارات فحص وصول النسخ الاحتياطية للوجهة الخارجية + سلوك الرفع
(`app/cli/backup.py`: `upload_offsite` · `check_offsite_freshness` ·
`cli_check_freshness`، §٩ — قرار المالك ٢٠٢٦-٠٩: `BACKUP_OFFSITE_DIR`
مجلد مُزامَن سحابياً).

لا `pg_dump` هنا — نظام ملفات + `Setting` فقط. كل عنصر يَعِد بسلوك
(تحذير عند غياب المجلد · تنبيه عند تقادم النسخة) يُختبَر أنه يُنتج الأثر
فعلاً، لا مظهره.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Setting

BACKUP_NAME = "wamda-20260903T030000Z.dump.enc"


# ── check_offsite_freshness ────────────────────────────────────────────


def test_freshness_not_configured_is_stale(monkeypatch):
    from app.cli.backup import check_offsite_freshness

    monkeypatch.setattr(settings, "backup_offsite_dir", None)
    result = check_offsite_freshness()
    assert result["configured"] is False
    assert result["stale"] is True
    assert "BACKUP_OFFSITE_DIR" in result["reason"]


def test_freshness_configured_but_dir_missing_is_stale(monkeypatch, tmp_path):
    from app.cli.backup import check_offsite_freshness

    monkeypatch.setattr(settings, "backup_offsite_dir", str(tmp_path / "not-mounted"))
    result = check_offsite_freshness()
    assert result["configured"] is True
    assert result["stale"] is True
    assert "غير موجود" in result["reason"]


def test_freshness_dir_exists_but_empty_is_stale(monkeypatch, tmp_path):
    from app.cli.backup import check_offsite_freshness

    monkeypatch.setattr(settings, "backup_offsite_dir", str(tmp_path))
    result = check_offsite_freshness()
    assert result["stale"] is True
    assert "لا نسخ" in result["reason"]


def test_freshness_recent_backup_is_not_stale(monkeypatch, tmp_path):
    from app.cli.backup import check_offsite_freshness

    (tmp_path / BACKUP_NAME).write_bytes(b"enc")
    monkeypatch.setattr(settings, "backup_offsite_dir", str(tmp_path))
    result = check_offsite_freshness()
    assert result["stale"] is False
    assert result["newest_file"] == BACKUP_NAME
    assert result["reason"] is None


def test_freshness_old_backup_is_stale(monkeypatch, tmp_path):
    from app.cli.backup import check_offsite_freshness

    old_file = tmp_path / BACKUP_NAME
    old_file.write_bytes(b"enc")
    fifty_hours_ago = time.time() - 50 * 3600
    os.utime(old_file, (fifty_hours_ago, fifty_hours_ago))
    monkeypatch.setattr(settings, "backup_offsite_dir", str(tmp_path))

    result = check_offsite_freshness()
    assert result["stale"] is True
    assert "٤٨" in result["reason"] or "48" in result["reason"]


def test_freshness_ignores_unrelated_files(monkeypatch, tmp_path):
    from app.cli.backup import check_offsite_freshness

    (tmp_path / "notes.txt").write_bytes(b"x")
    (tmp_path / "wamda-old.dump").write_bytes(b"x")  # غير مُشفَّر — لا يُحتسَب
    monkeypatch.setattr(settings, "backup_offsite_dir", str(tmp_path))
    result = check_offsite_freshness()
    assert result["stale"] is True  # لا ملف .dump.enc فعلي


# ── upload_offsite — تحذير صريح لا فشل صامت ─────────────────────────────


def test_upload_offsite_missing_dir_warns_and_does_not_create_it(monkeypatch, tmp_path):
    from app.cli.backup import upload_offsite

    payload = tmp_path / BACKUP_NAME
    payload.write_bytes(b"enc")
    missing = tmp_path / "sync-folder-not-there"
    monkeypatch.setattr(settings, "backup_offsite_dir", str(missing))

    result = upload_offsite(file_path=payload)
    assert result["status"] == "failed"
    assert "غير موجود" in result["detail"]
    assert not missing.exists()  # لم يُنشَأ تلقائياً — يُخفي عطل أداة المزامنة


def test_upload_offsite_unwritable_dir_warns(monkeypatch, tmp_path):
    from app.cli import backup

    payload = tmp_path / BACKUP_NAME
    payload.write_bytes(b"enc")
    dest = tmp_path / "sync"
    dest.mkdir()
    monkeypatch.setattr(settings, "backup_offsite_dir", str(dest))
    # os.access W_OK غير موثوق على ويندوز لمجلد للقراءة فقط — نحقن الرفض
    monkeypatch.setattr(backup.os, "access", lambda *a, **k: False)

    result = backup.upload_offsite(file_path=payload)
    assert result["status"] == "failed"
    assert "غير قابل للكتابة" in result["detail"]


def test_upload_offsite_ok_copies_file(monkeypatch, tmp_path):
    from app.cli.backup import upload_offsite

    payload = tmp_path / BACKUP_NAME
    payload.write_bytes(b"encrypted-bytes")
    dest = tmp_path / "sync"
    dest.mkdir()
    monkeypatch.setattr(settings, "backup_offsite_dir", str(dest))

    result = upload_offsite(file_path=payload)
    assert result["status"] == "ok"
    assert (dest / BACKUP_NAME).read_bytes() == b"encrypted-bytes"


def test_upload_offsite_not_configured_is_information_not_error(monkeypatch, tmp_path):
    from app.cli.backup import upload_offsite

    payload = tmp_path / BACKUP_NAME
    payload.write_bytes(b"enc")
    monkeypatch.setattr(settings, "backup_offsite_dir", None)
    monkeypatch.setattr(settings, "backup_sftp_host", None)

    result = upload_offsite(file_path=payload)
    assert result["status"] == "not_configured"
    assert result["detail"] is None


# ── cli_check_freshness — يكتب Setting ويقرأه تنبيه لوحة التحكم ─────────


def _read_freshness_setting(db):
    from app.cli.backup import BACKUP_FRESHNESS_SETTING_KEY

    row = db.execute(
        select(Setting).where(Setting.key == BACKUP_FRESHNESS_SETTING_KEY)
    ).scalar_one_or_none()
    return row.value if row else None


def test_cli_check_freshness_persists_stale_result_and_exits_nonzero(db, monkeypatch, tmp_path, capsys):
    from app.cli import backup

    import app.database as database_mod

    # مضبوط لكن المجلد غير موجود ⇒ stale
    monkeypatch.setattr(settings, "backup_offsite_dir", str(tmp_path / "missing"))
    monkeypatch.setattr(database_mod, "SessionLocal", lambda: db)  # backup.py يستورده داخل الدالة
    monkeypatch.setattr(db, "close", lambda: None)  # db fixture يُغلَق نفسه

    with pytest.raises(SystemExit) as exc_info:
        backup.cli_check_freshness()
    assert exc_info.value.code == 1

    value = _read_freshness_setting(db)
    assert value["stale"] is True
    assert "checked_at" in value  # متى جرى الفحص المجدول نفسه (للتحقق الشهري)
    assert "لوحة التحكم" in capsys.readouterr().out


def test_cli_check_freshness_persists_ok_result_and_exits_zero(db, monkeypatch, tmp_path):
    from app.cli import backup

    import app.database as database_mod

    (tmp_path / BACKUP_NAME).write_bytes(b"enc")
    monkeypatch.setattr(settings, "backup_offsite_dir", str(tmp_path))
    monkeypatch.setattr(database_mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)

    with pytest.raises(SystemExit) as exc_info:
        backup.cli_check_freshness()
    assert exc_info.value.code == 0

    value = _read_freshness_setting(db)
    assert value["stale"] is False
    assert value["newest_file"] == BACKUP_NAME
