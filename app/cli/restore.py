"""استعادة نسخة احتياطية — عبر CLI فقط، لا زر واجهة على الإنتاج إطلاقاً
(§٩، قرار مالك صريح). عمليتان:

  restore        فكّ التشفير واستعادة فعلية إلى قاعدة بيانات — تُدمِّر كل
                 بيانات تلك القاعدة الحالية (--clean). تأكيد كتابي إلزامي
                 صريح (نفس نمط purge_demo_data.py) بلا استثناء.
  restore-test   استعادة إلى قاعدة **مؤقتة** جديدة (تُنشَأ ثم تُحذَف تلقائياً
                 بعد الفحص) + recompute-balances --verify عليها — لا يمسّ
                 أي قاعدة حقيقية، آمن للتشغيل الدوري المجدول للتأكد أن
                 النسخ الاحتياطية فعلاً قابلة للاستعادة لا مجرد موجودة.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Optional

from app.cli.backup import BackupError, decrypt_file
from app.cli.pg_tools import PgToolError, connection_params, create_database, database_url_for, drop_database, run_pg_restore


def restore_into(*, backup_path: Path, target_database_url: str) -> None:
    tmp_dir = backup_path.parent
    decrypted_path = tmp_dir / f".{backup_path.stem}.decrypted"
    try:
        decrypt_file(input_path=backup_path, output_path=decrypted_path)
        params = connection_params(target_database_url)
        run_pg_restore(params=params, input_path=decrypted_path)
    finally:
        if decrypted_path.exists():
            decrypted_path.unlink()


class VerifyOutcome:
    def __init__(self, *, ok: bool, report) -> None:
        self.ok = ok
        self.report = report


def restore_test(*, backup_path: Path) -> VerifyOutcome:
    """استعادة إلى قاعدة مؤقتة عشوائية الاسم + recompute-balances --verify
    عليها، ثم حذفها دائماً (نجح الفحص أم لا)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.engine import recompute

    temp_db_name = f"wamda_restore_test_{uuid.uuid4().hex[:12]}"
    create_database(temp_db_name)
    try:
        restore_into(backup_path=backup_path, target_database_url=database_url_for(temp_db_name))

        engine = create_engine(database_url_for(temp_db_name))
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            report = recompute.verify(db)
        finally:
            db.close()
            engine.dispose()
        return VerifyOutcome(ok=report.ok, report=report)
    finally:
        drop_database(temp_db_name)


def cli_restore(backup_file: str, target_db: Optional[str], confirm_text: Optional[str]) -> None:
    if not target_db:
        print("--target-db إلزامي — لا استعادة بلا وجهة صريحة")
        sys.exit(1)
    print(
        f"هذا سيُدمِّر كل بيانات قاعدة \"{target_db}\" الحالية ويستبدلها بمحتوى "
        f"النسخة الاحتياطية بلا رجعة."
    )
    if confirm_text != "RESTORE":
        typed = input('اكتب RESTORE (بالإنجليزية) للتأكيد: ').strip()
        if typed != "RESTORE":
            print("أُلغي — لم تُستعَد أي بيانات.")
            sys.exit(1)

    try:
        target_url = database_url_for(target_db)
        restore_into(backup_path=Path(backup_file), target_database_url=target_url)
    except (BackupError, PgToolError) as exc:
        print(f"فشلت الاستعادة: {exc}")
        sys.exit(1)
    print(f"اكتملت الاستعادة إلى \"{target_db}\" — شغّل recompute-balances --verify للتأكد.")


def cli_restore_test(backup_file: str) -> None:
    try:
        outcome = restore_test(backup_path=Path(backup_file))
    except (BackupError, PgToolError) as exc:
        print(f"فشل اختبار الاستعادة: {exc}")
        sys.exit(1)

    if outcome.ok:
        print("اختبار الاستعادة: نجح — استعادة كاملة + recompute-balances --verify بصفر اختلاف.")
        sys.exit(0)
    print("اختبار الاستعادة: فشل — النسخة الاحتياطية استُعيدت لكن الأرصدة غير متسقة:")
    for d in outcome.report.balance_diffs:
        print(f"  فرق رصيد {d.account_code}: مخزَّن={d.cached} محسوب={d.computed}")
    for p in outcome.report.swift_problems:
        print(f"  سويفت: {p}")
    for p in outcome.report.lot_problems:
        print(f"  دفعة: {p}")
    sys.exit(1)
