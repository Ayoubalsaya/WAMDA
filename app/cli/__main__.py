"""python -m app.cli <command> — §3-8: recompute-balances --verify إلزامي لاحقاً."""

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    # طرفية ويندوز الافتراضية cp1252 لا تعرض العربية — الإخراج UTF-8 دائماً
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="زرع بيانات التهيئة: العملات · المواقع · شجرة الحسابات")

    args = parser.parse_args()

    if args.command == "seed":
        from app.cli.seed import run

        run()
    else:  # pragma: no cover
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
