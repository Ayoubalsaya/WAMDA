"""فحص السلامة اليومي المجدول (§٩) — أهم إنذار في النظام: يعيد استخدام
`recompute.verify` (نفس فحص `recompute-balances --verify`، بلا تكرار
منطق) ويحفظ آخر نتيجة في `Setting` (key="last_integrity_check") ليقرأها
`dashboard._compute_alerts` قراءة رخيصة بدل إعادة حساب كامل عند كل تحميل
شاشة — تنبيه "فوري" يعني: يظهر فوراً لأول موظف يفتح لوحة التحكم بعد فشل
الفحص، لا قناة تنبيه خارجية (بريد/واتساب) — لا خدمة إشعار مُهيَّأة في
المشروع بعد.

لا `audit_log` هنا عمداً — actor_type محصور USER/CLIENT (ENUM قاعدة بيانات
حقيقي، §٥ قاعدة ١١)، ولا "فاعل" حقيقياً لمهمة نظامية مجدولة؛ `Setting`
هو المخزن الصحيح لحالة نظامية حالية لا سجل فعل مُساءَل عنه.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.engine import recompute
from app.models import Setting

INTEGRITY_CHECK_SETTING_KEY = "last_integrity_check"


def run() -> None:
    db = SessionLocal()
    try:
        report = recompute.verify(db)
        now = datetime.now(timezone.utc)
        value = {
            "ok": report.ok,
            "checked_at": now.isoformat(),
            "balance_diff_count": len(report.balance_diffs),
            "swift_problem_count": len(report.swift_problems),
            "lot_problem_count": len(report.lot_problems),
            "commission_problem_count": len(getattr(report, "commission_problems", [])),
        }
        row = db.execute(select(Setting).where(Setting.key == INTEGRITY_CHECK_SETTING_KEY)).scalar_one_or_none()
        if row is None:
            db.add(Setting(key=INTEGRITY_CHECK_SETTING_KEY, value=value))
        else:
            row.value = value
        db.commit()

        if report.ok:
            print("daily-integrity-check: صفر اختلاف — كل شيء متسق.")
            sys.exit(0)

        print("daily-integrity-check: ⚠ اختلاف حقيقي — سيظهر تنبيه فوري في لوحة التحكم:")
        for d in report.balance_diffs:
            print(f"  فرق رصيد {d.account_code}: مخزَّن={d.cached} محسوب={d.computed}")
        for p in report.swift_problems:
            print(f"  سويفت: {p}")
        for p in report.lot_problems:
            print(f"  دفعة: {p}")
        for p in getattr(report, "commission_problems", []):
            print(f"  عمولة: {p}")
        sys.exit(1)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
