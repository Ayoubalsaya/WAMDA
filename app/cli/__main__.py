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
        sys.exit(0 if report.ok else 1)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


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

    args = parser.parse_args()

    if args.command == "seed":
        _cmd_seed()
    elif args.command == "recompute-balances":
        _cmd_recompute_balances(verify_only=args.verify)
    else:  # pragma: no cover
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
