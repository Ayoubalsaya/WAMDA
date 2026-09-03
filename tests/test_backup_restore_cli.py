"""اختبارات النسخ الاحتياطي والاستعادة (`app/cli/backup.py`،
`app/cli/restore.py`، `app/cli/pg_tools.py`، §٩ المرحلة ١١).

**تحذير نطاق**: هذه الاختبارات تُشغِّل `pg_dump`/`pg_restore`/`psql` حقيقيين
عبر subprocess ضد قاعدة التطوير الفعلية (قراءة فقط لـpg_dump — لا كتابة
عليها إطلاقاً) و/أو قواعد بيانات مؤقتة تُنشَأ وتُحذَف بأسماء عشوائية
(`wamda_restore_test_*`) — لا تلمس `wamda_db` نفسها بالكتابة أبداً. تتطلب
`BACKUP_ENCRYPTION_KEY`/`PG_DUMP_PATH`/`PG_RESTORE_PATH`/`PSQL_PATH` في
`.env` المحلي؛ تُهمَل تلقائياً (skip) إن لم تُضبَط بيئياً بدل الفشل الصامت.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.config import settings

pytestmark = pytest.mark.skipif(
    not settings.backup_encryption_key, reason="BACKUP_ENCRYPTION_KEY غير مضبوط محلياً — لا يمكن اختبار التشفير"
)


@pytest.fixture()
def tmp_backup_dir(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_encrypt_decrypt_round_trip(tmp_path):
    from app.cli.backup import decrypt_file, encrypt_file

    plain = tmp_path / "plain.bin"
    plain.write_bytes(b"WAMDA-BACKUP-TEST-CONTENT-\x00\x01\x02" * 100)
    encrypted = tmp_path / "plain.bin.enc"
    encrypt_file(input_path=plain, output_path=encrypted)
    assert encrypted.read_bytes() != plain.read_bytes()

    decrypted = tmp_path / "plain.bin.dec"
    decrypt_file(input_path=encrypted, output_path=decrypted)
    assert decrypted.read_bytes() == plain.read_bytes()


def test_decrypt_wrong_key_fails_clearly(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    from app.cli.backup import BackupError, decrypt_file, encrypt_file

    plain = tmp_path / "plain.bin"
    plain.write_bytes(b"secret dump content")
    encrypted = tmp_path / "plain.bin.enc"
    encrypt_file(input_path=plain, output_path=encrypted)

    monkeypatch.setattr(settings, "backup_encryption_key", Fernet.generate_key().decode())
    with pytest.raises(BackupError):
        decrypt_file(input_path=encrypted, output_path=tmp_path / "out.bin")


@pytest.mark.skipif(not settings.pg_dump_path, reason="PG_DUMP_PATH غير مضبوط محلياً")
def test_run_pg_dump_produces_real_custom_format_file(tmp_path):
    from app.cli.pg_tools import connection_params, run_pg_dump

    params = connection_params(settings.database_url)
    output = tmp_path / "test.dump"
    run_pg_dump(params=params, output_path=output)
    assert output.exists()
    assert output.stat().st_size > 0
    # تنسيق pg_dump المخصَّص (-Fc) يبدأ دائماً بتوقيع "PGDMP" — تأكيد أن
    # الملف مُخرَج pg_dump حقيقي لا ملفاً فارغاً/تالفاً
    assert output.read_bytes()[:5] == b"PGDMP"


@pytest.mark.skipif(not settings.pg_dump_path, reason="PG_DUMP_PATH غير مضبوط محلياً")
def test_backup_run_creates_encrypted_file_deletes_plaintext_and_copies_offsite(tmp_backup_dir):
    from app.cli import backup

    result = backup.run(dest_dir=tmp_backup_dir)
    encrypted_path = Path(result["local_path"])
    assert encrypted_path.exists()
    assert result["size_bytes"] > 0
    # لا نسخة غير مُشفَّرة تبقى على القرص أبداً
    plain_candidates = list(tmp_backup_dir.glob("*.dump"))
    assert plain_candidates == []

    if settings.backup_offsite_dir and Path(settings.backup_offsite_dir).is_dir():
        offsite_copy = Path(settings.backup_offsite_dir) / encrypted_path.name
        assert offsite_copy.exists()
        assert offsite_copy.read_bytes() == encrypted_path.read_bytes()
        assert result["upload_status"] == "ok"
        offsite_copy.unlink()
    elif settings.backup_offsite_dir:
        # مضبوط لكن المجلد غير موجود — تحذير صريح لا فشل صامت، لا نسخة تُنشأ
        assert result["upload_status"] == "failed"
    else:
        assert result["upload_status"] == "not_configured"


def test_backup_fails_loudly_without_encryption_key(tmp_backup_dir, monkeypatch):
    from app.cli import backup
    from app.cli.backup import BackupError

    monkeypatch.setattr(settings, "backup_encryption_key", None)
    with pytest.raises(BackupError):
        backup.run(dest_dir=tmp_backup_dir)


@pytest.mark.skipif(
    not (settings.pg_dump_path and settings.backup_admin_database_url or settings.pg_dump_path),
    reason="أدوات Postgres غير مضبوطة محلياً",
)
def test_restore_test_full_cycle_against_real_backup(tmp_backup_dir):
    """الفحص الشامل الحقيقي المطلوب صراحة: نسخة احتياطية حقيقية → استعادة
    إلى قاعدة مؤقتة حقيقية (تُحذَف تلقائياً) → recompute-balances --verify
    عليها. يتطلب CREATEDB على الدور المُهيَّأ في DATABASE_URL (أو
    BACKUP_ADMIN_DATABASE_URL منفصلاً)."""
    from app.cli import backup
    from app.cli.restore import restore_test

    result = backup.run(dest_dir=tmp_backup_dir)
    outcome = restore_test(backup_path=Path(result["local_path"]))
    assert outcome.ok, (
        f"استعادة القاعدة المؤقتة نجحت لكن recompute-balances --verify وجد اختلافاً: "
        f"{len(outcome.report.balance_diffs)} فرق رصيد"
    )


def test_cli_restore_refuses_without_typed_confirmation(tmp_backup_dir, monkeypatch, capsys):
    """--target-db بلا تأكيد كتابي RESTORE → رفض فوري، بنفس نمط purge_demo_data.py."""
    from app.cli.restore import cli_restore

    monkeypatch.setattr("builtins.input", lambda _: "not-the-right-word")
    with pytest.raises(SystemExit) as exc_info:
        cli_restore("does-not-matter.dump.enc", "some_target_db", confirm_text=None)
    assert exc_info.value.code == 1
    assert "أُلغي" in capsys.readouterr().out
