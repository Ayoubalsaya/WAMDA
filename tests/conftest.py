"""تجهيزات pytest المشتركة — المرحلة ٣.

عزل كل اختبار بمعاملة قاعدة بيانات واحدة تُلغى (rollback) نهاية الاختبار.
محرك القيود (`app.engine.*`) لا يستدعي `commit()` أبداً بتصميمه — المستدعي
يتحكم به دائماً — فهذا يعطي عزلاً كاملاً حقيقياً (Postgres فعلي: triggers،
FKs، `SELECT…FOR UPDATE`) بلا إعادة بناء مخطط بين الاختبارات وبلا حيلة
savepoint إضافية، وبلا أي أثر يبقى في قاعدة التطوير.

اختبارات التزامن الحقيقية (threads/processes بجلسات/اتصالات منفصلة —
اختبارات القبول ١٧ · ٤٣ · ٤٤ · ٤٥) لا يمكنها استخدام هذه العزلة (تحتاج
commit فعلياً لتُظهر تنافس الأقفال بين اتصالات مستقلة) — لها تجهيزاتها
الخاصة في tests/test_concurrency.py.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import pytest

if hasattr(sys.stdout, "reconfigure"):
    # طرفية ويندوز الافتراضية cp1252 لا تعرض العربية — الإخراج UTF-8 دائماً
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings

WORK_TZ = settings.work_timezone

# وقت ثابت محقون لكل الاختبارات غير التزامنية — لا datetime.now في أي اختبار.
FIXED_NOW = datetime(2026, 6, 15, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(settings.database_url)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session", autouse=True)
def _ensure_seeded(engine):
    """يتأكد أن بيانات التهيئة (§٣-١/٣-٢) موجودة قبل أي اختبار — بمعاملة
    فعلية منفصلة مُلتزَمة (commit)، مرة واحدة لكامل جلسة الاختبارات. لا
    يُعيد بناء المخطط ولا يمسّ بيانات موجودة — يزرع فقط إن كان فارغاً.
    """
    from app.models import Currency

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        if session.execute(select(Currency)).first() is None:
            from app.cli.seed import run as seed_run

            seed_run()
    finally:
        session.close()


@pytest.fixture()
def db(engine):
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        # اختبار قد يسبب خطأ SQL مباشر (تريجر يرفض UPDATE مثلاً) يُنهي
        # المعاملة من طرف الخادم فعلياً قبل وصولنا هنا — transaction.rollback()
        # حينها عملية محلية بلا أثر خادم، وSQLAlchemy يُحذّر بلا داعٍ.
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture()
def now() -> datetime:
    return FIXED_NOW


# ── تغطية اختبارات القبول ١-٥٠ (§١١) — يجعل تقرير التغطية موثوقاً لا ادعاءً ──
TOTAL_ACCEPTANCE_TESTS = 50


def pytest_collection_modifyitems(config, items):
    """يُجمع بعد كل تجميع اختبارات: يفحص كل `@pytest.mark.acceptance(n)` أن
    `1 ≤ n ≤ 50` (فشل فوري على أي خطأ كتابي)، ويخزّن خريطة {رقم: [عقد الاختبارات]}
    على `config` ليقرأها `tests/test_marker_coverage.py`.
    """
    coverage: dict[int, list[str]] = {}
    bad: list[str] = []
    for item in items:
        for mark in item.iter_markers(name="acceptance"):
            (n,) = mark.args
            if not isinstance(n, int) or not (1 <= n <= TOTAL_ACCEPTANCE_TESTS):
                bad.append(f"{item.nodeid}: acceptance({n!r}) خارج المدى ١-{TOTAL_ACCEPTANCE_TESTS}")
                continue
            coverage.setdefault(n, []).append(item.nodeid)

    if bad:
        raise pytest.UsageError("علامات acceptance غير صالحة:\n" + "\n".join(bad))

    config._acceptance_coverage = coverage
