"""قفل جلسة الاختبارات (٢٠٢٦-١٠-١٢): تشغيلان لـpytest معاً على `wamda_test` يتعارضان ويعلقان بصمت — يُمنع تقنياً.

`pg_try_advisory_lock(k1, k2)` على اتصال يبقى مفتوحاً طوال الجلسة. يُحرَّر تلقائياً إن ماتت العملية (يُغلق السوكيت)، فلا ملف
قفل «يتيم» يمنع التشغيل التالي. الاتصال بقاعدة الصيانة `postgres` لا بـ`wamda_test` نفسها: القاعدة قد لا تكون موجودة بعد في أول
تشغيل (`_ensure_schema` ينشئها)، ولو اختلفت قاعدة القفل بين تشغيلين لما تنافيا. المفتاح مشتقّ من اسم قاعدة الاختبار فتُقفَل كل قاعدة
اختبار على حدة (`TEST_DATABASE_URL` مختلف = تشغيل مستقل مسموح)."""

from __future__ import annotations

import re
import zlib
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

LOCK_NAMESPACE = 0x57414D44  # «WAMD»


def database_name(url: str) -> str:
    return re.search(r"/([^/?]+)(\?.*)?$", url).group(1)


def lock_key(dbname: str) -> tuple[int, int]:
    return LOCK_NAMESPACE, zlib.crc32(dbname.encode()) & 0x7FFFFFFF


class SessionLock:
    def __init__(self, database_url: str, *, label: str):
        self.dbname = database_name(database_url)
        self.key = lock_key(self.dbname)
        maintenance = re.sub(r"/[^/?]+(\?.*)?$", lambda m: "/postgres" + (m.group(1) or ""), database_url)
        self._engine = create_engine(
            maintenance, poolclass=NullPool, isolation_level="AUTOCOMMIT", connect_args={"application_name": label}
        )
        self._conn = None

    def acquire(self) -> bool:
        """يحاول أخذ القفل دون انتظار. `True` = أُخذ (والاتصال يبقى مفتوحاً)، `False` = بيد تشغيل آخر."""
        conn = self._engine.connect()
        got = conn.execute(text("SELECT pg_try_advisory_lock(:a, :b)"), {"a": self.key[0], "b": self.key[1]}).scalar()
        if got:
            self._conn = conn
        else:
            conn.close()
        return bool(got)

    def holder(self) -> Optional[str]:
        """وصف صاحب القفل الحالي (التسمية + وقت اتصاله) إن أمكن — للرسالة فقط."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT a.application_name, a.backend_start FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                    "WHERE l.locktype = 'advisory' AND l.granted AND l.classid = :a AND l.objid = :b LIMIT 1"
                ),
                {"a": self.key[0], "b": self.key[1]},
            ).first()
        return f"{row[0]}، بدأ {row[1]:%Y-%m-%d %H:%M:%S}" if row else None

    def release(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()  # إغلاق الجلسة يحرّر القفل
            finally:
                self._conn = None
        self._engine.dispose()
