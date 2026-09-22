"""تجهيزات pytest المشتركة — المرحلتان ٣ و٤.

عزل كل اختبار بمعاملة قاعدة بيانات واحدة تُلغى (rollback) نهاية الاختبار،
عبر نمط SQLAlchemy القياسي "الانضمام لمعاملة خارجية" بـSAVEPOINT: محرك
القيود (`app.engine.*`) لا يستدعي `commit()` أبداً، لكن طبقة المصادقة
(`app/routers/auth.py`) تستدعيه فعلياً كما تفعل أي واجهة HTTP حقيقية —
`commit()` عادي على جلسة مربوطة باتصال بمعاملة خارجية بدأها الاختبار
يُنهي *تلك المعاملة نفسها* لا savepoint وهمياً، فينكسر العزل بصمت بين
طلبين متتاليين في نفس الاختبار. مستمع `after_transaction_end` يعيد فتح
SAVEPOINT تلقائياً بعد كل commit/rollback داخلي، فيبقى كل شيء قابلاً
للإلغاء الكامل حتى النهاية بصرف النظر عن عدد مرات commit() من الكود
قيد الاختبار.

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
from sqlalchemy import create_engine, event, select
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
    outer_transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    session.begin_nested()  # SAVEPOINT أول — الكود قيد الاختبار يعمل ضمنه

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(session_, transaction):
        # commit()/rollback() داخل الكود قيد الاختبار (مثل app/routers/auth.py)
        # ينهي الـ SAVEPOINT الحالي فقط — نعيد فتح واحد جديد فوراً كي تبقى
        # المعاملة الخارجية (outer_transaction) هي الحدود الحقيقية الوحيدة.
        if transaction.nested and not transaction._parent.nested:
            session_.begin_nested()

    try:
        yield session
    finally:
        event.remove(session, "after_transaction_end", _restart_savepoint)
        session.close()
        # اختبار قد يسبب خطأ SQL مباشر (تريجر يرفض UPDATE مثلاً) يُنهي
        # المعاملة من طرف الخادم فعلياً قبل وصولنا هنا — rollback() حينها
        # عملية محلية بلا أثر خادم، وSQLAlchemy يُحذّر بلا داعٍ.
        if outer_transaction.is_active:
            outer_transaction.rollback()
        connection.close()


@pytest.fixture()
def now() -> datetime:
    return FIXED_NOW


@pytest.fixture(autouse=True)
def _reset_login_rate_limiters():
    """عدّادات تحديد معدل الدخول (§٩ المرحلة ١٢) حالتها على مستوى الوحدة —
    تُصفَّر قبل كل اختبار كي لا تتسرّب محاولات دخول اختبار إلى التالي."""
    from app.security import deps

    deps._login_rate_limiter.reset()
    deps._portal_login_rate_limiter.reset()
    yield


# ── تغطية اختبارات القبول ١-٥٠ (§١١) — يجعل تقرير التغطية موثوقاً لا ادعاءً ──
TOTAL_ACCEPTANCE_TESTS = 50

# اختبارات قبول لا يمكن التعبير عنها في pytest headless (تحتاج متصفحاً حياً
# وواجهة مبنية)، لكن لها **سكربت تحقُّق Playwright حقيقي ملتزَم** يُشغَّل قبل
# كل عرض ونتيجته توثَّق في PROGRESS.md. تُعدّ مغطّاة كي لا تبقى علامة حمراء
# دائمة تفقد معناها (قرار المرحلة ١٢).
ACCEPTANCE_VERIFIED_VIA_PLAYWRIGHT: dict[int, str] = {
    50: "RTL/أرقام LTR/محاذاة أعمدة/أيقونات — scripts/verify_acceptance_50_rtl.py",
}

# اختبارات قبول أُلغيت عمداً — البند الوظيفي الذي تختبره لم يعد موجوداً في
# النظام، لا نقصاً في التغطية. تُعدّ مغطّاة هنا كي لا يُظهرها `marker-coverage`
# "مفقودة" زوراً (قرار المرحلة نفسها موثَّق في PROGRESS.md).
ACCEPTANCE_CANCELLED: dict[int, str] = {
    31: "مستفيد إلزامي في REMIT_OUT — سجل المستفيدين أُلغي بالكامل (قرار مالك ٢٠٢٦-٠٩-٢٢)",
    32: "رقم حساب إلزامي عند إنشاء مستفيد — نفس الإلغاء أعلاه",
    33: "لقطة وجهة التحويل (RemitOutDestination) — نفس الإلغاء أعلاه",
}


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
