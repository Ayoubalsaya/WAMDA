"""`backup` يفشل (exit ≠ 0) إن فشل الرفع، ويتحقق من وصول الملف (٢٠٢٦-١٠-٠٦، تدقيق U-07).

قبل الإصلاح: فرع `failed` (وغير المضبوط) يطبع تحذيراً ويخرج ٠ فيظنّ المجدول/المشغّل أن النسخة بخير؛ والنسخ إلى المجلد الخارجي لا يتحقق
من أن الملف وصل كاملاً (قرص ممتلئ/نسخة مبتورة)؛ وفشل الكتابة نفسه (OSError) كان استثناءً خاماً."""

from __future__ import annotations

import shutil

import pytest

from app.cli import backup
from app.config import settings


@pytest.fixture()
def payload(tmp_path):
    p = tmp_path / "wamda-20261006T000000Z.dump.enc"
    p.write_bytes(b"x" * 4096)
    return p


def _offsite(monkeypatch, tmp_path):
    dest = tmp_path / "sync"
    dest.mkdir()
    monkeypatch.setattr(settings, "backup_offsite_dir", str(dest))
    monkeypatch.setattr(settings, "backup_sftp_host", None)
    return dest


def test_upload_verifies_the_copy_arrived_complete(monkeypatch, tmp_path, payload):
    dest = _offsite(monkeypatch, tmp_path)
    result = backup.upload_offsite(file_path=payload)
    assert result["status"] == "ok" and (dest / payload.name).read_bytes() == payload.read_bytes()


def test_truncated_copy_is_a_failure_and_leaves_no_partial_file(monkeypatch, tmp_path, payload):
    dest = _offsite(monkeypatch, tmp_path)

    def truncated_copy(src, dst, **kw):
        open(dst, "wb").write(open(src, "rb").read()[:100])

    monkeypatch.setattr(shutil, "copy2", truncated_copy)
    result = backup.upload_offsite(file_path=payload)
    assert result["status"] == "failed" and "لم يصل كاملاً" in result["detail"]
    assert not (dest / payload.name).exists(), "نسخة مبتورة في مجلد المزامنة تُرفَع للسحابة كأنها سليمة"


def test_corrupted_copy_same_size_is_a_failure(monkeypatch, tmp_path, payload):
    _offsite(monkeypatch, tmp_path)
    monkeypatch.setattr(shutil, "copy2", lambda src, dst, **kw: open(dst, "wb").write(b"y" * 4096))
    assert backup.upload_offsite(file_path=payload)["status"] == "failed"


def test_write_error_is_a_failure_not_a_raw_exception(monkeypatch, tmp_path, payload):
    _offsite(monkeypatch, tmp_path)

    def boom(src, dst, **kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(shutil, "copy2", boom)
    result = backup.upload_offsite(file_path=payload)
    assert result["status"] == "failed" and "No space left" in result["detail"]


def test_sftp_is_no_longer_supported_and_says_so(monkeypatch, tmp_path, payload):
    monkeypatch.setattr(settings, "backup_offsite_dir", None)
    monkeypatch.setattr(settings, "backup_sftp_host", "example.invalid")
    result = backup.upload_offsite(file_path=payload)
    assert result["status"] == "failed" and "BACKUP_OFFSITE_DIR" in result["detail"]


def _run_with(monkeypatch, upload_status, app_env="local"):
    monkeypatch.setattr(settings, "app_env", app_env)
    monkeypatch.setattr(backup, "run", lambda: {"local_path": "b.enc", "size_bytes": 1, "upload_status": upload_status, "upload_detail": "x", "timestamp": "t"})
    with pytest.raises(SystemExit) as exc:
        backup.cli_run()
        raise SystemExit(0)  # لم يخرج بكود: نجاح
    return exc.value.code


def test_cli_exits_nonzero_when_the_upload_failed(monkeypatch):
    assert _run_with(monkeypatch, "failed") not in (0, None)


def test_cli_exits_zero_when_the_upload_succeeded(monkeypatch):
    assert _run_with(monkeypatch, "ok") in (0, None)


def test_cli_unconfigured_offsite_fails_in_production_only(monkeypatch):
    assert _run_with(monkeypatch, "not_configured", app_env="production") not in (0, None)
    assert _run_with(monkeypatch, "not_configured", app_env="local") in (0, None)
