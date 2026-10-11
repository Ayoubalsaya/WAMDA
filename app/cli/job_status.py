"""حالة المهام المجدولة (systemd timers) لتظهر في لوحة التحكم إلى أن يُعدّ البريد (٢٠٢٦-١٠-١٢، قرار مالك).

`OnFailure=` في كل وحدة مهمة يستدعي `job-status <job> --failed`، و`ExecStartPost=` يستدعي `job-status <job> --ok` عند النجاح
(فيزول التنبيه تلقائياً بأول نجاح لاحق). الحالة في `Setting` (key=`job_status:<job>`) — نفس نمط `last_integrity_check`؛ لا
`audit_log` (لا فاعل USER/CLIENT لمهمة نظامية)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Setting

# اسم المهمة (كما في وحدات systemd: wamda-<job>.service) ← الوصف العربي في التنبيه
JOB_LABELS_AR: dict[str, str] = {
    "backup": "النسخ الاحتياطي",
    "integrity": "فحص السلامة اليومي",
    "backup-fresh": "فحص وصول النسخ الاحتياطية",
    "restore-test": "اختبار الاستعادة الأسبوعي",
}
SETTING_PREFIX = "job_status:"


def setting_key(job: str) -> str:
    return f"{SETTING_PREFIX}{job}"


def record(job: str, *, ok: bool, now: datetime | None = None, db=None) -> dict:
    """`db`: جلسة مُمرَّرة (اختبارات) تُستخدَم وتُفلَش بلا commit؛ بدونها تُفتح جلسة وتُلتزَم."""
    if job not in JOB_LABELS_AR:
        raise ValueError(f"مهمة غير معروفة: {job} (المسموح: {', '.join(sorted(JOB_LABELS_AR))})")
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    value = {"ok": True, "at": stamp} if ok else {"ok": False, "failed_at": stamp}
    own = db is None
    session = SessionLocal() if own else db
    try:
        row = session.execute(select(Setting).where(Setting.key == setting_key(job))).scalar_one_or_none()
        if row is None:
            session.add(Setting(key=setting_key(job), value=value))
        else:
            row.value = value
        if own:
            session.commit()
        else:
            session.flush()
    finally:
        if own:
            session.close()
    return value


def run(job: str, *, ok: bool) -> None:
    value = record(job, ok=ok)
    print(f"job-status: {job} = {'OK' if ok else 'FAILED'} ({value.get('at') or value.get('failed_at')})")
