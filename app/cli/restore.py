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
from app.cli.pg_tools import (
    PgToolError, connection_params, create_database, database_url_for, drop_database, list_databases, run_pg_restore,
)


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


RESTORE_TEST_PREFIX = "wamda_restore_test_"


def sweep_stale_restore_databases() -> list[str]:
    """يحذف أي قاعدة مؤقتة يتيمة من تشغيلات سابقة. تُرجِع ما حُذف. لا تمسّ إلا هذه البادئة حصراً."""
    dropped = []
    for name in list_databases(RESTORE_TEST_PREFIX):
        drop_database(name)
        dropped.append(name)
    if dropped:
        print(f"كُنست قواعد مؤقتة يتيمة من تشغيلات سابقة: {', '.join(dropped)}", file=sys.stderr)
    return dropped


def restore_test(*, backup_path: Path) -> VerifyOutcome:
    """استعادة إلى قاعدة مؤقتة عشوائية الاسم + recompute-balances --verify
    عليها، ثم حذفها دائماً (نجح الفحص أم لا)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.engine import recompute

    # ٢٠٢٦-١٠-٠٣: الأداة تعمل أسبوعياً على السيرفر — يجب ألا تترك قاعدة مؤقتة أبداً.
    # (١) كنس الأيتام: قاعدة `wamda_restore_test_*` تركتها تشغيلة سابقة ماتت قسراً (kill/انقطاع) تُحذف قبل البدء؛
    # (٢) الحذف في `finally` دائماً — نجح الفحص أم فشل أم قُطع (KeyboardInterrupt/SIGTERM)؛
    # (٣) الحذف يتحقق من الغياب ويعيد المحاولة ويرفع خطأً صريحاً إن بقيت القاعدة (لا فشل صامت).
    sweep_stale_restore_databases()
    completed = False  # اكتمل المسار الرئيسي بلا استثناء (لا يُعتمد على sys.exc_info: يتأثر بسياق المستدعي)
    temp_db_name = f"{RESTORE_TEST_PREFIX}{uuid.uuid4().hex[:12]}"
    try:
        create_database(temp_db_name)
        restore_into(backup_path=backup_path, target_database_url=database_url_for(temp_db_name))

        engine = create_engine(database_url_for(temp_db_name))
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            report = recompute.verify(db)
        finally:
            db.close()
            engine.dispose()
        completed = True
        return VerifyOutcome(ok=report.ok, report=report)
    finally:
        try:
            drop_database(temp_db_name)
        except PgToolError as exc:
            if completed:
                raise  # لا استثناء جارٍ: الفشل في الحذف هو الخطأ نفسه، يظهر للمشغِّل (exit 1)
            # استثناء أصلي جارٍ (فشل الاستعادة/الفحص): يبقى هو الظاهر، ويُطبَع تحذير الحذف
            print(f"⚠ {exc}", file=sys.stderr)


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
    import signal

    def _terminate(_signum, _frame):  # SIGTERM (systemd/cron timeout) ← استثناء فيعمل `finally` ويُحذف المؤقت
        raise SystemExit(143)

    try:
        signal.signal(signal.SIGTERM, _terminate)
    except (ValueError, OSError):  # خيط غير رئيسي/نظام بلا SIGTERM
        pass
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
    for p in getattr(outcome.report, "commission_problems", []):
        print(f"  عمولة: {p}")
    sys.exit(1)
