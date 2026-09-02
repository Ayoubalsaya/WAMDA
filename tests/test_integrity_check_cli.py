"""اختبارات فحص السلامة اليومي (`app/cli/integrity_check.py`، §٩ المرحلة ١١)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Setting


def test_daily_integrity_check_persists_ok_result(db):
    from app.cli.integrity_check import INTEGRITY_CHECK_SETTING_KEY

    # يعمل مباشرة على معاملة db المعزولة — لا SessionLocal حقيقية (نفس
    # درس test_cli_purge_demo_data.py)
    from app.engine import recompute

    report = recompute.verify(db)
    assert report.ok  # القاعدة نظيفة أصلاً حسب baseline معروف هذه الجلسة

    value = {
        "ok": report.ok, "checked_at": "2026-06-15T10:00:00+00:00",
        "balance_diff_count": 0, "swift_problem_count": 0, "lot_problem_count": 0,
    }
    # Setting.key مفتاح أساسي حقيقي — صف بهذا المفتاح موجود فعلياً في قاعدة
    # التطوير (من تشغيل حقيقي لـ`daily-integrity-check`)، فتحقُّق-ثم-تحديث/
    # إدراج لا إدراج أعمى (نفس منطق app.cli.integrity_check.run نفسه)
    existing = db.execute(select(Setting).where(Setting.key == INTEGRITY_CHECK_SETTING_KEY)).scalar_one_or_none()
    if existing is None:
        db.add(Setting(key=INTEGRITY_CHECK_SETTING_KEY, value=value))
    else:
        existing.value = value
    db.flush()

    row = db.execute(select(Setting).where(Setting.key == INTEGRITY_CHECK_SETTING_KEY)).scalar_one()
    assert row.value["ok"] is True


def test_daily_integrity_check_cli_exits_nonzero_on_mismatch(db, monkeypatch):
    """يحاكي اختلافاً حقيقياً (بدل إفساد بيانات حقيقية) بمحاكاة رد
    `recompute.verify` — يتحقق فقط من مسار الكتابة/الخروج، لا من منطق
    `recompute.verify` نفسه (مُختبَر بالكامل في مكانه الأصلي)."""
    import sys

    from app.cli import integrity_check
    from app.engine import recompute

    class _FakeReport:
        ok = False
        balance_diffs = [type("D", (), {"account_code": "1101", "cached": "100", "computed": "90"})()]
        swift_problems = []
        lot_problems = []

    monkeypatch.setattr(recompute, "verify", lambda _db: _FakeReport())
    monkeypatch.setattr(integrity_check, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)  # db fixture يُغلَق نفسه لاحقاً، لا داخل هذا الاستدعاء

    with pytest.raises(SystemExit) as exc_info:
        integrity_check.run()
    assert exc_info.value.code == 1

    row = db.execute(select(Setting).where(Setting.key == integrity_check.INTEGRITY_CHECK_SETTING_KEY)).scalar_one()
    assert row.value["ok"] is False
    assert row.value["balance_diff_count"] == 1
