"""نسخ احتياطي يومي مُشفَّر + رفع خارج السيرفر (§٩).

pg_dump -Fc → تشفير Fernet → حذف النسخة غير المُشفَّرة فوراً (لا نسخة
صريحة على القرص أبداً، حتى لحظياً بعد اكتمال التشفير) → رفع لوجهة خارجية
إن أُعِدَّت (مجلد "خارج سيرفر" مُركَّب أو SFTP). وجهة الرفع النهائية قرار
مالك معلَّق (انظر PROGRESS.md) — الآلية هنا عامة وتعمل بأي منهما، وتُحذِّر
بوضوح بدل الفشل الصامت إن لم تُضبَط أي وجهة بعد.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.cli.pg_tools import PgToolError, connection_params, run_pg_dump
from app.config import settings


class BackupError(Exception):
    pass


def encrypt_file(*, input_path: Path, output_path: Path) -> Path:
    if not settings.backup_encryption_key:
        raise BackupError("BACKUP_ENCRYPTION_KEY غير مضبوط — التشفير إلزامي، لا نسخة غير مُشفَّرة تُكتَب أبداً")
    from cryptography.fernet import Fernet

    fernet = Fernet(settings.backup_encryption_key.encode())
    output_path.write_bytes(fernet.encrypt(input_path.read_bytes()))
    return output_path


def decrypt_file(*, input_path: Path, output_path: Path) -> Path:
    if not settings.backup_encryption_key:
        raise BackupError("BACKUP_ENCRYPTION_KEY غير مضبوط")
    from cryptography.fernet import Fernet, InvalidToken

    fernet = Fernet(settings.backup_encryption_key.encode())
    try:
        output_path.write_bytes(fernet.decrypt(input_path.read_bytes()))
    except InvalidToken as exc:
        raise BackupError("فشل فكّ التشفير — مفتاح خاطئ أو ملف تالف") from exc
    return output_path


def upload_offsite(*, file_path: Path) -> Optional[str]:
    """يُعيد وصف الوجهة عند نجاح الرفع، أو None إن لم تُضبَط أي وجهة."""
    if settings.backup_offsite_dir:
        dest_dir = Path(settings.backup_offsite_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / file_path.name
        shutil.copy2(file_path, dest)
        return f"offsite-dir:{dest}"
    if settings.backup_sftp_host:
        import paramiko

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            settings.backup_sftp_host, port=settings.backup_sftp_port, username=settings.backup_sftp_user,
            key_filename=settings.backup_sftp_key_path,
        )
        try:
            sftp = ssh.open_sftp()
            remote_dir = (settings.backup_sftp_remote_dir or ".").rstrip("/")
            remote_path = f"{remote_dir}/{file_path.name}"
            sftp.put(str(file_path), remote_path)
            sftp.close()
        finally:
            ssh.close()
        return f"sftp:{settings.backup_sftp_host}:{remote_path}"
    return None


def run(*, dest_dir: Optional[Path] = None) -> dict:
    """نسخة احتياطية كاملة. يُعيد ملخّصاً: المسار المحلي المُشفَّر، حجمه،
    وجهة الرفع (أو None إن لم تُضبَط)."""
    if not settings.backup_encryption_key:
        # فشل مبكر قبل أي pg_dump — لا عمل ضائع، ولا نسخة غير مُشفَّرة
        # تُكتَب على القرص حتى لحظياً
        raise BackupError("BACKUP_ENCRYPTION_KEY غير مضبوط — التشفير إلزامي، لا نسخة غير مُشفَّرة تُكتَب أبداً")

    dest_dir = dest_dir or Path("backups")
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    plain_path = dest_dir / f"wamda-{stamp}.dump"
    encrypted_path = dest_dir / f"wamda-{stamp}.dump.enc"

    try:
        params = connection_params(settings.database_url)
        run_pg_dump(params=params, output_path=plain_path)
        encrypt_file(input_path=plain_path, output_path=encrypted_path)
    finally:
        if plain_path.exists():
            plain_path.unlink()

    destination = upload_offsite(file_path=encrypted_path)
    return {
        "local_path": str(encrypted_path),
        "size_bytes": encrypted_path.stat().st_size,
        "offsite_destination": destination,
        "timestamp": stamp,
    }


def cli_run() -> None:
    import sys

    try:
        result = run()
    except (BackupError, PgToolError) as exc:
        print(f"فشل النسخ الاحتياطي: {exc}")
        sys.exit(1)

    print(f"نسخة احتياطية مُشفَّرة: {result['local_path']} ({result['size_bytes']} بايت)")
    if result["offsite_destination"]:
        print(f"رُفعت إلى: {result['offsite_destination']}")
    else:
        print(
            "تحذير: لا وجهة رفع خارجية مضبوطة (BACKUP_OFFSITE_DIR/BACKUP_SFTP_*) — "
            "النسخة محلية فقط على هذا السيرفر. قرار الوجهة لا يزال معلَّقاً عند المالك."
        )
