"""نسخ احتياطي يومي مُشفَّر + رفع خارج السيرفر (§٩).

pg_dump -Fc → تشفير Fernet → حذف النسخة غير المُشفَّرة فوراً (لا نسخة
صريحة على القرص أبداً، حتى لحظياً بعد اكتمال التشفير) → نسخ إلى وجهة
خارجية إن أُعِدَّت.

**قرار المالك (٢٠٢٦-٠٩، المرحلة ١٢):** الوجهة الخارجية هي `BACKUP_OFFSITE_DIR`
— مجلد محلي على السيرفر تُزامنه أداة سحابية (Google Drive / OneDrive أو
مكافئ) إلى خارج السيرفر. لا SFTP ولا مزوّد إضافي: النسخة تُكتَب في المجلد
وأداة المزامنة ترفعها. آلية SFTP (`BACKUP_SFTP_*`) تبقى في الكود كبديل
شبكي مباشر غير مستخدَم.

الاعتماد على أداة مزامنة خارج عمليتنا يعني أننا لا نملك تأكيداً برمجياً
لحظياً أن الملف وصل السحابة فعلاً — لذلك:
· `upload_offsite` **لا يُنشئ** المجلد تلقائياً؛ غيابه/تعذُّر الكتابة فيه
  تحذير صريح لا فشل صامت (المجلد يجب أن يكون مجلد أداة المزامنة الحقيقي).
· `check_offsite_freshness` (أمر `check-backup-freshness` المجدول) يفحص
  أن أحدث نسخة في المجلد أُنشئت خلال ٤٨ ساعة — أي أطول ⇒ تنبيه critical
  في لوحة التحكم بجانب تنبيه فحص السلامة.
· تحقُّق يدوي شهري إلزامي أن الملفات تصل السحابة فعلاً — انظر README.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.cli.pg_tools import PgToolError, connection_params, run_pg_dump
from app.config import settings

_BACKUP_GLOB = "wamda-*.dump.enc"


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


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_offsite(*, file_path: Path) -> dict:
    """status: "ok" (رُفعت فعلاً) · "not_configured" (لا وجهة مضبوطة —
    معلومة لا خطأ) · "failed" (وجهة مضبوطة لكن تعذَّر الوصول إليها — تحذير
    حقيقي، **لا يُنشئ مجلداً بديلاً محلياً بصمت** حتى لا تبدو نسخة محلية
    عارضة كأنها وصلت الوجهة الحقيقية)."""
    if settings.backup_offsite_dir:
        dest_dir = Path(settings.backup_offsite_dir)
        # لا mkdir هنا عمداً — هذا المجلد يجب أن يكون مجلد أداة المزامنة
        # السحابية الحقيقي (Google Drive/OneDrive وما يعادلهما)، لا مساراً
        # نُنشئه نحن. إن لم يكن موجوداً فهذا دليل أن أداة المزامنة غير
        # مثبَّتة/تعمل أو أن المسار خطأ — إنشاؤه تلقائياً يُخفي هذه الحقيقة.
        if not dest_dir.exists():
            return {
                "status": "failed",
                "detail": (
                    f"مجلد الرفع الخارجي غير موجود: {dest_dir} — تأكد أن أداة المزامنة "
                    "السحابية مثبَّتة وتعمل فعلياً وأن BACKUP_OFFSITE_DIR يشير للمسار الصحيح"
                ),
            }
        if not os.access(dest_dir, os.W_OK):
            return {"status": "failed", "detail": f"مجلد الرفع الخارجي غير قابل للكتابة: {dest_dir}"}
        dest = dest_dir / file_path.name
        try:
            shutil.copy2(file_path, dest)
        except OSError as exc:  # قرص ممتلئ/صلاحيات/انقطاع مجلد مركَّب — فشل صريح لا استثناء خام بعد أن أُنشئت النسخة المحلية
            dest.unlink(missing_ok=True)
            return {"status": "failed", "detail": f"فشل النسخ إلى المجلد الخارجي: {exc}"}
        # تحقق من الوصول: الملف موجود بالحجم نفسه وبالمحتوى نفسه (SHA-256). نسخة مبتورة/تالفة في مجلد المزامنة
        # تُرفَع للسحابة كأنها سليمة — تُحذَف فوراً ويُعلَن الفشل. (وصول الملف للسحابة نفسها لا يُرى من هنا: انظر check_offsite_freshness.)
        try:
            arrived = dest.exists() and dest.stat().st_size == file_path.stat().st_size and _sha256(dest) == _sha256(file_path)
        except OSError as exc:
            dest.unlink(missing_ok=True)
            return {"status": "failed", "detail": f"تعذّر التحقق من وصول الملف: {exc}"}
        if not arrived:
            dest.unlink(missing_ok=True)
            return {"status": "failed", "detail": f"الملف لم يصل كاملاً إلى {dest_dir} (حجم/تجزئة مختلفان) — حُذفت النسخة المعطوبة"}
        return {"status": "ok", "detail": f"offsite-dir:{dest}"}
    if settings.backup_sftp_host:
        # SFTP أُلغي (قرار المالك: مجلد المزامنة فقط) — كان مساراً غير مستخدَم باعتماد غير مُعلَن (paramiko) وقبول مفاتيح مضيف تلقائياً
        return {"status": "failed", "detail": "BACKUP_SFTP_HOST لم يعد مدعوماً — اضبط BACKUP_OFFSITE_DIR (مجلد أداة المزامنة)"}
    return {"status": "not_configured", "detail": None}


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

    upload_result = upload_offsite(file_path=encrypted_path)
    return {
        "local_path": str(encrypted_path),
        "size_bytes": encrypted_path.stat().st_size,
        "upload_status": upload_result["status"],
        "upload_detail": upload_result["detail"],
        "timestamp": stamp,
    }


def check_offsite_freshness(*, max_age_hours: int = 48) -> dict:
    """يفحص وجهة الرفع الخارجية **نفسها** (لا القرص المحلي) — نسخة احتياطية
    محلية ناجحة لكن لم تصل الوجهة الحقيقية أخطر من نسخة لم تُنشأ إطلاقاً
    (قد تُظَنّ آمنة بالخطأ). يدعم آلية المجلد المُركَّب فقط حالياً — SFTP
    يحتاج اتصالاً حياً لفحص الطرف البعيد، غير مُنفَّذ بعد (فجوة موثَّقة)."""
    if not settings.backup_offsite_dir:
        return {"configured": False, "stale": True, "reason": "لا وجهة رفع خارجية مضبوطة (BACKUP_OFFSITE_DIR)"}
    dest_dir = Path(settings.backup_offsite_dir)
    if not dest_dir.exists():
        return {"configured": True, "stale": True, "reason": f"مجلد الرفع الخارجي غير موجود: {dest_dir}"}
    backups = sorted(dest_dir.glob(_BACKUP_GLOB), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        return {"configured": True, "stale": True, "reason": "لا نسخ احتياطية وصلت المجلد الخارجي إطلاقاً"}
    newest = backups[0]
    age_hours = (time.time() - newest.stat().st_mtime) / 3600
    stale = age_hours > max_age_hours
    return {
        "configured": True, "stale": stale, "newest_file": newest.name,
        "age_hours": round(age_hours, 1),
        "reason": None if not stale else f"آخر نسخة وصلت المجلد الخارجي منذ {round(age_hours, 1)} ساعة (> {max_age_hours})",
    }


def cli_run() -> None:
    import sys

    try:
        result = run()
    except (BackupError, PgToolError) as exc:
        print(f"فشل النسخ الاحتياطي: {exc}")
        sys.exit(1)

    print(f"نسخة احتياطية مُشفَّرة: {result['local_path']} ({result['size_bytes']} بايت)")
    if result["upload_status"] == "ok":
        print(f"رُفعت إلى: {result['upload_detail']}")
        return
    # exit ≠ 0 حتى يرى المجدول/المشغّل الفشل (كان يخرج ٠ بتحذير مطبوع فقط). النسخة المحلية تبقى سليمة على القرص.
    if result["upload_status"] == "failed":
        print(f"✗ فشل الرفع الخارجي: {result['upload_detail']}")
        print("النسخة محلية فقط على هذا السيرفر — راجع الوجهة المضبوطة فوراً.")
        sys.exit(2)
    msg = "لا وجهة رفع خارجية مضبوطة (BACKUP_OFFSITE_DIR) — النسخة محلية فقط على هذا السيرفر."
    if settings.app_env == "production":
        print(f"✗ {msg}")
        sys.exit(2)
    print(f"تحذير: {msg}")


BACKUP_FRESHNESS_SETTING_KEY = "last_backup_freshness_check"


def cli_check_freshness() -> None:
    """يُشغَّل مجدولاً (مستقل عن `backup` نفسها عمداً — توقُّف مهمة النسخ
    الاحتياطي كلياً عن العمل يجب أن يُكتشَف أيضاً، لا فقط فشل رفع نسخة
    أُنشئت فعلاً). يحفظ النتيجة في `Setting` ليقرأها تنبيه لوحة التحكم —
    نفس نمط `app.cli.integrity_check` تماماً، بجانبه لا بديلاً عنه."""
    import sys
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Setting

    result = check_offsite_freshness()
    # `checked_at` = متى جرى هذا الفحص المجدول نفسه (لا عمر أحدث ملف) —
    # يسمح للتحقق الشهري اليدوي (انظر README) بمعرفة آخر مرة عمل فيها
    # الفحص التلقائي أصلاً، تماماً كـ`last_integrity_check`.
    stored = {**result, "checked_at": datetime.now(timezone.utc).isoformat()}
    db = SessionLocal()
    try:
        row = db.execute(select(Setting).where(Setting.key == BACKUP_FRESHNESS_SETTING_KEY)).scalar_one_or_none()
        if row is None:
            db.add(Setting(key=BACKUP_FRESHNESS_SETTING_KEY, value=stored))
        else:
            row.value = stored
        db.commit()
    finally:
        db.close()

    if not result["stale"]:
        print(f"فحص وصول النسخ الاحتياطية: سليم — آخر نسخة منذ {result['age_hours']} ساعة ({result['newest_file']}).")
        sys.exit(0)
    print(f"⚠ فحص وصول النسخ الاحتياطية: {result['reason']} — سيظهر تنبيه فوري في لوحة التحكم.")
    sys.exit(1)
