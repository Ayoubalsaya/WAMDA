"""بيانات التهيئة (المرحلة ١) — §3-1 / §3-2 / §10.

يزرع: العملات · المواقع · شجرة الحسابات الأساسية (غير المرتبطة بشركاء
بعد — المكاتب والمراسلون الفعليون بيانات تشغيلية تُدخَل لاحقاً عبر
شاشة الشركاء لا هنا) · عدّادات وتخصيصات ترقيم الحسابات الفرعية للعملات
· إعداد منطقة العمل · صف الفترة التأسيسية الوحيد.

قابل لإعادة التشغيل بأمان (idempotent) — يتخطى ما هو موجود بالفعل.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    Account,
    AccountNumberAssignment,
    AccountNumberCounter,
    Currency,
    FoundingPeriod,
    Location,
    Setting,
)
from app.models.enums import AccountType
from app.config import settings

# §3-1 — الترتيب يحدد تسلسل الترقيم الفرعي (account_number_counters) لاحقاً
CURRENCIES = [
    dict(code="LYD", name_ar="دينار ليبي", symbol="د.ل", decimals=3, is_pivot=False, sort_order=1),
    dict(code="USD", name_ar="دولار أمريكي", symbol="$", decimals=2, is_pivot=True, sort_order=2),
    dict(code="CNY", name_ar="يوان صيني (رمبي)", symbol="¥", decimals=2, is_pivot=False, sort_order=3),
]

LOCATIONS = [
    dict(code="TRIPOLI", name_ar="طرابلس", country="LY"),
    dict(code="BENGHAZI", name_ar="بنغازي", country="LY"),
    dict(code="LIBYA_BANK", name_ar="مصرفي ليبيا", country="LY"),
    dict(code="TURKEY", name_ar="تركيا", country="TR"),
    dict(code="CHINA", name_ar="الصين", country="CN"),
]


def _seed_currencies(db: Session) -> dict[str, Currency]:
    existing = {c.code: c for c in db.query(Currency).all()}
    for data in CURRENCIES:
        if data["code"] in existing:
            continue
        row = Currency(**data)
        db.add(row)
        existing[data["code"]] = row
    db.flush()
    return existing


def _seed_locations(db: Session) -> dict[str, Location]:
    existing = {l.code: l for l in db.query(Location).all()}
    for data in LOCATIONS:
        if data["code"] in existing:
            continue
        row = Location(**data)
        db.add(row)
        db.flush()
        existing[data["code"]] = row
    return existing


def _get_or_create_account(
    db: Session,
    by_code: dict[str, Account],
    *,
    code: str,
    name_ar: str,
    type_: AccountType,
    currency_code: str | None = None,
    location_id: int | None = None,
    form: str | None = None,
    parent_code: str | None = None,
    is_system: bool = True,
) -> Account:
    if code in by_code:
        return by_code[code]
    parent_id = by_code[parent_code].id if parent_code else None
    row = Account(
        code=code,
        name_ar=name_ar,
        type=type_,
        currency_code=currency_code,
        location_id=location_id,
        form=form,
        parent_id=parent_id,
        is_system=is_system,
    )
    db.add(row)
    db.flush()
    by_code[code] = row
    return row


def _subdivide_by_currency(
    db: Session,
    by_code: dict[str, Account],
    parent: Account,
    currencies: list[Currency],
) -> list[Account]:
    """§3-2 — تخصيص متسلسل تحت الأب، idempotent، بترتيب currencies.sort_order.

    يطابق آلية account_number_counters/account_number_assignments بالضبط:
    لا يُعاد استخدام رقم، والتخصيص الحالي يُقرأ أولاً قبل أي تسلسل جديد.
    """
    created: list[Account] = []
    counter = db.get(AccountNumberCounter, parent.id)
    if counter is None:
        counter = AccountNumberCounter(parent_id=parent.id, next_suffix=1)
        db.add(counter)
        db.flush()

    for ccy in sorted(currencies, key=lambda c: c.sort_order):
        assignment = db.get(AccountNumberAssignment, (parent.id, ccy.code))
        if assignment is None:
            suffix = counter.next_suffix
            # ٤١١٠→٤١١١/٤١١٢… : الرقم الفرعي يستبدل الصفر الأخير من كود الأب،
            # لا يُضاف بعده (والده دائماً ينتهي بصفر بحسب شجرة §3-2).
            assigned_code = f"{parent.code[:-1]}{suffix}"
            assignment = AccountNumberAssignment(
                parent_id=parent.id, currency_code=ccy.code, assigned_code=assigned_code
            )
            db.add(assignment)
            counter.next_suffix = suffix + 1
            db.flush()
        child = _get_or_create_account(
            db,
            by_code,
            code=assignment.assigned_code,
            name_ar=f"{parent.name_ar} · {ccy.name_ar}",
            type_=parent.type,
            currency_code=ccy.code,
            parent_code=parent.code,
            is_system=True,
        )
        created.append(child)
    return created


def _seed_chart_of_accounts(
    db: Session, currencies: dict[str, Currency], locations: dict[str, Location]
) -> None:
    by_code: dict[str, Account] = {a.code: a for a in db.query(Account).all()}
    ccy_list = list(currencies.values())

    def acc(code, name_ar, type_, **kw):
        return _get_or_create_account(db, by_code, code=code, name_ar=name_ar, type_=type_, **kw)

    def sub(parent_code):
        return _subdivide_by_currency(db, by_code, by_code[parent_code], ccy_list)

    # ── ١٠٠٠ الأصول ──────────────────────────────────────────────────────
    acc("1000", "الأصول", AccountType.ASSET)
    acc("1100", "الصناديق النقدية المباشرة", AccountType.ASSET, parent_code="1000")
    acc(
        "1101", "دينار · طرابلس · كاش", AccountType.ASSET,
        currency_code="LYD", location_id=locations["TRIPOLI"].id, form="CASH", parent_code="1100",
    )
    acc(
        "1102", "دينار · بنغازي · كاش", AccountType.ASSET,
        currency_code="LYD", location_id=locations["BENGHAZI"].id, form="CASH", parent_code="1100",
    )
    acc(
        "1103", "دينار · مصرفي ليبيا", AccountType.ASSET,
        currency_code="LYD", location_id=locations["LIBYA_BANK"].id, form="BANK", parent_code="1100",
    )
    # ⚠ 1104 بلا موقع محدد (طرابلس/بنغازي) — الوثيقة تكتبه "دولار · ليبيا · كاش"
    # على مستوى الدولة لا المدينة، خلافاً لـ 1101/1102. مرتبط بقرار معلّق
    # (عدد مكاتب ليبيا) — راجع الملخص المرفق مع هذا التشغيل.
    acc("1104", "دولار · ليبيا · كاش", AccountType.ASSET, currency_code="USD", form="CASH", parent_code="1100")

    acc("1300", "حسابات المراسلين", AccountType.ASSET, parent_code="1000")
    # 1310/1320 رؤوس فقط هنا — حسابات المكاتب/الشركات الفعلية (1311، 1321..)
    # تُنشأ عند تسجيل الشريك الحقيقي في شاشة الشركاء، لا كبيانات تهيئة مصطنعة.
    acc("1310", "مراسلو ليبيا", AccountType.ASSET, parent_code="1300")
    acc("1320", "مراسلو تركيا", AccountType.ASSET, parent_code="1300")

    acc("1400", "حسابات بنكية مملوكة", AccountType.ASSET, parent_code="1000")
    # كذلك 1410/1420 (بنوك الصين الفعلية) تُنشأ عند تسجيلها لاحقاً.

    acc("1500", "تحويلات في الطريق", AccountType.ASSET, parent_code="1000")
    acc(
        "1501", "سويفت تركيا ← الصين (USD)", AccountType.ASSET,
        currency_code="USD", form="CLEARING", parent_code="1500",
    )

    acc("1900", "مقاصة الصرف", AccountType.ASSET, parent_code="1000", form="CLEARING")
    sub("1900")

    # ── ٢٠٠٠ الالتزامات ──────────────────────────────────────────────────
    acc("2000", "الالتزامات", AccountType.LIABILITY)
    # 2100 رأس فقط — حسابات العملاء تُشتق حتمياً 2100-{code}-{ccy}-{loc}
    # وتُنشأ كسولاً عند أول استخدام (التعديل المعتمد §٣)، لا تُزرع هنا.
    acc("2100", "حسابات العملاء", AccountType.LIABILITY, parent_code="2000")

    # ── ٣٠٠٠ حقوق الملكية ────────────────────────────────────────────────
    acc("3000", "حقوق الملكية", AccountType.EQUITY)
    acc("3100", "رأس المال", AccountType.EQUITY, parent_code="3000")
    sub("3100")
    acc("3200", "الأرباح المحتجزة", AccountType.EQUITY, parent_code="3000")
    sub("3200")
    acc("3900", "فروق تأسيسية تحت المصالحة", AccountType.EQUITY, parent_code="3000")
    sub("3900")

    # ── ٤٠٠٠ الإيرادات ───────────────────────────────────────────────────
    acc("4000", "الإيرادات", AccountType.REVENUE)
    acc("4110", "إيرادات فرق التحويل", AccountType.REVENUE, parent_code="4000")
    sub("4110")
    acc("4120", "أرباح فروق أسعار الصرف", AccountType.REVENUE, parent_code="4000")
    sub("4120")
    acc("4900", "زيادة الصندوق", AccountType.REVENUE, parent_code="4000")
    sub("4900")

    # ── ٥٠٠٠ المصروفات ───────────────────────────────────────────────────
    acc("5000", "المصروفات", AccountType.EXPENSE)
    acc("5120", "خسائر فروق أسعار الصرف", AccountType.EXPENSE, parent_code="5000")
    sub("5120")
    # ⚠ 5200/5300 ليسا في قائمة التفريع المعتمدة (التعديل رقم ٢ خصّ 3100/3200
    # فقط) فبقيا بعملة واحدة كما في الوثيقة الأصلية: 5300 بالدولار — يطابق
    # مثال §4-1 السويفت حرفياً (رسوم 25 ضمن قيد بالدولار) — و5200 بالدينار
    # كافتراض تشغيلي محلي. إن استلزم الواقع عملات أخرى لأي منهما أخبرني
    # لأفرّعهما بنفس آلية 3100/3200/3900 دون أي إعادة كتابة.
    acc("5200", "مصروفات تشغيلية", AccountType.EXPENSE, currency_code="LYD", parent_code="5000")
    acc("5300", "رسوم بنكية وسويفت", AccountType.EXPENSE, currency_code="USD", parent_code="5000")
    acc("5410", "تكلفة فرق التحويل", AccountType.EXPENSE, parent_code="5000")
    sub("5410")
    # ⚠ 5900 بلا عملة (NULL) عمداً — الوثيقة تنص "حساب واحد" لكل فروق التقريب
    # عبر كل العملات معاً (§2-5)، بخلاف كل الحسابات الأخرى المفرَّعة أعلاه.
    # تريجر مطابقة العملة (journal_lines) يستثني الحسابات NULL العملة تحديداً
    # لأجل هذا الحساب وحده.
    acc("5900", "فروق التقريب", AccountType.EXPENSE, parent_code="5000")
    acc("5910", "عجز الصندوق", AccountType.EXPENSE, parent_code="5000")
    sub("5910")


def _seed_founding_period(db: Session) -> None:
    if db.get(FoundingPeriod, 1) is None:
        db.add(FoundingPeriod(id=1, is_open=True))


def _seed_settings(db: Session) -> None:
    if db.get(Setting, "work_timezone") is None:
        db.add(Setting(key="work_timezone", value={"value": settings.work_timezone}))


def run() -> None:
    db = SessionLocal()
    try:
        currencies = _seed_currencies(db)
        locations = _seed_locations(db)
        _seed_chart_of_accounts(db, currencies, locations)
        _seed_founding_period(db)
        _seed_settings(db)
        db.commit()
        print("تمت التهيئة بنجاح.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
