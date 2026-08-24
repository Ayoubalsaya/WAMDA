"""§٥ قاعدة ٩ — entry_no / chain_ref / lot_no: بلا فجوات، قفل صفّي، لا إعادة استخدام.

كل تخصيص يجري **داخل معاملة قاعدة البيانات الجارية** (لا معاملة خاصة به) —
فشل المعاملة المحيطة يُرجع العدّاد معها فلا تنشأ فجوة، تماماً كما تنص الوثيقة.
"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Counter

_PREFIXES: dict[str, tuple[str, int]] = {
    "WMD": ("WMD-{year}-{seq:06d}", 6),
    "CHN": ("CHN-{year}-{seq:06d}", 6),
    "LOT": ("LOT-{year}-{seq:04d}", 4),
}


def _locked_counter(db: Session, name: str, year: int) -> Counter:
    """أول استخدام لهذا (name, year): `pg_advisory_xact_lock` يُسلسل كل
    الطلبات المتزامنة لنفس المفتاح *قبل* أي فحص — بنفس أسلوب
    `idempotency.run`/`accounts_repo.get_or_create_client_account` تماماً،
    لا `begin_nested()` يدوي. (تصحيح معتمد بعد مراجعة المرحلة ٥: النمط
    السابق بـ`with db.begin_nested()` كان يتصادم مع مستمع إعادة فتح
    الـSAVEPOINT في عزل اختبارات pytest بعد أي `commit()` سابق من طبقة
    HTTP — أول مسار حقيقي عبر الشبكة يُنشئ رقماً طازجاً كشف هذا.)
    """
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key)::bigint)"), {"key": f"counter:{name}:{year}"})
    counter = db.execute(
        select(Counter).where(Counter.name == name, Counter.year == year).with_for_update()
    ).scalar_one_or_none()
    if counter is None:
        counter = Counter(name=name, year=year, last_value=0)
        db.add(counter)
        db.flush()
    return counter


def next_number(db: Session, name: str, year: int) -> str:
    """يخصّص الرقم التالي لعائلة `name` (`WMD`/`CHN`/`LOT`) في سنة `year`."""
    template, _width = _PREFIXES[name]
    counter = _locked_counter(db, name, year)
    counter.last_value += 1
    db.flush()
    return template.format(year=year, seq=counter.last_value)


def next_entry_no(db: Session, year: int) -> str:
    return next_number(db, "WMD", year)


def next_chain_ref(db: Session, year: int) -> str:
    return next_number(db, "CHN", year)


def next_lot_no(db: Session, year: int) -> str:
    return next_number(db, "LOT", year)
