"""python -m app.cli <command> — §3-8."""

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    # طرفية ويندوز الافتراضية cp1252 لا تعرض العربية — الإخراج UTF-8 دائماً
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _cmd_seed() -> None:
    from app.cli.seed import run

    run()


def _cmd_recompute_balances(verify_only: bool) -> None:
    from app.database import SessionLocal
    from app.engine import recompute

    db = SessionLocal()
    try:
        report = recompute.verify(db) if verify_only else recompute.rebuild(db)
        if not verify_only:
            db.commit()

        if report.ok:
            print("recompute-balances: صفر اختلاف — كل شيء متسق.")
        else:
            for d in report.balance_diffs:
                print(f"  فرق رصيد {d.account_code}: مخزَّن={d.cached} محسوب={d.computed}")
            for p in report.swift_problems:
                print(f"  سويفت: {p}")
            for p in report.lot_problems:
                print(f"  دفعة: {p}")
            for p in report.commission_problems:
                print(f"  عمولة: {p}")
        sys.exit(0 if report.ok else 1)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _cmd_create_admin() -> None:
    from app.cli.create_admin import run

    run()


def _cmd_reset_2fa() -> None:
    from app.cli.reset_2fa import run

    run()


def _cmd_unlock_user() -> None:
    from app.cli.unlock_user import run

    run()


def _cmd_reset_admin_password() -> None:
    from app.cli.reset_admin_password import run

    run()


def _cmd_purge_demo_data() -> None:
    from app.cli.purge_demo_data import run

    run()


def _cmd_backup() -> None:
    from app.cli.backup import cli_run

    cli_run()


def _cmd_restore(backup_file: str, target_db: str | None) -> None:
    from app.cli.restore import cli_restore

    cli_restore(backup_file, target_db, confirm_text=None)


def _cmd_restore_test(backup_file: str | None, *, latest: bool = False) -> None:
    from app.cli.restore import cli_restore_test, latest_local_backup

    if bool(backup_file) == bool(latest):
        print("حدّد ملفاً واحداً أو --latest (لا الاثنين ولا لا شيء)")
        sys.exit(2)
    if latest:
        found = latest_local_backup()
        if found is None:
            print("لا نسخة محلية لاختبارها في BACKUP_DIR")
            sys.exit(1)
        backup_file = str(found)
    cli_restore_test(backup_file)


def _cmd_daily_integrity_check() -> None:
    from app.cli.integrity_check import run

    run()


def _cmd_check_backup_freshness() -> None:
    from app.cli.backup import cli_check_freshness

    cli_check_freshness()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="زرع بيانات التهيئة: العملات · المواقع · شجرة الحسابات")
    recompute_parser = sub.add_parser(
        "recompute-balances", help="إعادة بناء account_balances من journal_lines"
    )
    recompute_parser.add_argument(
        "--verify", action="store_true", help="فحص فقط بلا كتابة — يفشل (exit 1) عند أي اختلاف"
    )
    sub.add_parser("create-admin", help="إنشاء أول مدير (تفاعلي) — يرفض إن وُجد مدير بالفعل")
    sub.add_parser("reset-2fa", help="إعادة ضبط المصادقة الثنائية لمستخدم (فقدان الجهاز) من السيرفر — كلمة المرور لا تتغيّر")
    sub.add_parser("unlock-user", help="فك قفل حساب بعد محاولات فاشلة فوراً (لا يمسّ كلمة المرور ولا 2FA)")
    sub.add_parser("reset-admin-password", help="إعادة تعيين كلمة مرور مدير من السيرفر — طوارئ")
    sub.add_parser(
        "purge-demo-data",
        help="حذف عملاء/مستخدمي العرض والاختبار وقيودهم (تفاعلي، يطلب تأكيداً) — قبل إدخال بيانات حقيقية",
    )
    sub.add_parser("backup", help="نسخة احتياطية مُشفَّرة (pg_dump -Fc) + رفع خارج السيرفر إن أُعِدَّت وجهة")
    restore_parser = sub.add_parser(
        "restore", help="استعادة نسخة احتياطية إلى قاعدة بيانات محدَّدة — يُدمِّر بياناتها الحالية، تأكيد كتابي إلزامي"
    )
    restore_parser.add_argument("backup_file", help="مسار ملف .dump.enc")
    restore_parser.add_argument("--target-db", required=True, help="اسم قاعدة البيانات المستهدَفة")
    restore_test_parser = sub.add_parser(
        "restore-test", help="استعادة إلى قاعدة مؤقتة تُحذَف تلقائياً + recompute-balances --verify — آمن للتشغيل الدوري"
    )
    restore_test_parser.add_argument("backup_file", nargs="?", help="مسار ملف .dump.enc (أو --latest)")
    restore_test_parser.add_argument(
        "--latest", action="store_true", help="أحدث نسخة محلية في BACKUP_DIR (للمؤقّت الأسبوعي — بلا صدفة shell)"
    )
    sub.add_parser(
        "daily-integrity-check",
        help="recompute-balances --verify + حفظ النتيجة (Setting) لعرضها كتنبيه فوري في لوحة التحكم عند أي اختلاف",
    )
    job_status_parser = sub.add_parser(
        "job-status",
        help="يسجّل نجاح/فشل مهمة مجدولة في الإعدادات لتظهر في لوحة التحكم (يستدعيه systemd: OnFailure/ExecStartPost)",
    )
    from app.cli.job_status import JOB_LABELS_AR as _JOBS

    job_status_parser.add_argument("job", choices=sorted(_JOBS))
    job_status_group = job_status_parser.add_mutually_exclusive_group(required=True)
    job_status_group.add_argument("--failed", action="store_true")
    job_status_group.add_argument("--ok", action="store_true")
    sub.add_parser(
        "check-backup-freshness",
        help="يتحقق أن آخر نسخة احتياطية وصلت مجلد الرفع الخارجي فعلياً خلال ٤٨ ساعة — تنبيه فوري إن لم تصل",
    )

    args = parser.parse_args()

    if args.command == "seed":
        _cmd_seed()
    elif args.command == "recompute-balances":
        _cmd_recompute_balances(verify_only=args.verify)
    elif args.command == "create-admin":
        _cmd_create_admin()
    elif args.command == "reset-2fa":
        _cmd_reset_2fa()
    elif args.command == "unlock-user":
        _cmd_unlock_user()
    elif args.command == "reset-admin-password":
        _cmd_reset_admin_password()
    elif args.command == "purge-demo-data":
        _cmd_purge_demo_data()
    elif args.command == "backup":
        _cmd_backup()
    elif args.command == "restore":
        _cmd_restore(args.backup_file, args.target_db)
    elif args.command == "restore-test":
        _cmd_restore_test(args.backup_file, latest=args.latest)
    elif args.command == "daily-integrity-check":
        _cmd_daily_integrity_check()
    elif args.command == "job-status":
        from app.cli.job_status import run as _job_status_run

        _job_status_run(args.job, ok=bool(args.ok))
    elif args.command == "check-backup-freshness":
        _cmd_check_backup_freshness()
    else:  # pragma: no cover
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
