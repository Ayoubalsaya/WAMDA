"""بحث/اشتقاق الحسابات — النظامية منها وحسابات العملاء المُشتقة حتمياً.

لا منطق محاسبي هنا، مجرد بحث/إنشاء كسول. المنطق المحاسبي في posting.py
ووحدات operations/.
"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import (
    Account,
    AccountNumberAssignment,
    AccountNumberCounter,
    Client,
    ClientCurrencyLocation,
    Currency,
    Location,
)
from app.models.enums import AccountForm, AccountType


class AccountNotFoundError(Exception):
    pass


class InvalidClientLocationError(Exception):
    """§٢-٢ (تعديل معتمد): تركيبة عملة×موقع غير مسموح بها لحساب عميل —
    الإنشاء الكسول بلا قيد كان يولّد حساباً لا وجود له في الواقع."""


class AccountNumberExhaustedError(Exception):
    """§٣-٢: الرقم الفرعي يستبدل رقماً أخيراً واحداً من كود الأب (١-٩) —
    لا مجال لعاشر طفل تحت نفس الأب بهذا الترميز بلا تمديد الكود بالكامل،
    قرار مالك خارج نطاق هذا المحرك."""


def get_account_by_code(db: Session, code: str) -> Account:
    account = db.execute(select(Account).where(Account.code == code)).scalar_one_or_none()
    if account is None:
        raise AccountNotFoundError(f"لا حساب بالكود {code}")
    return account


def get_currency(db: Session, code: str) -> Currency:
    currency = db.get(Currency, code)
    if currency is None:
        raise AccountNotFoundError(f"لا عملة بالكود {code}")
    return currency


def get_pivot_currency(db: Session) -> Currency:
    """§٣-١: عملة محورية واحدة (`is_pivot`) — USD حالياً، لا تُثبَّت في الكود."""
    currency = db.execute(select(Currency).where(Currency.is_pivot.is_(True))).scalar_one_or_none()
    if currency is None:
        raise AccountNotFoundError("لا عملة محورية (is_pivot) مُعرَّفة")
    return currency


def get_location_by_code(db: Session, code: str) -> Location:
    location = db.execute(select(Location).where(Location.code == code)).scalar_one_or_none()
    if location is None:
        raise AccountNotFoundError(f"لا موقع بالكود {code}")
    return location


def get_currency_subaccount(db: Session, parent_code: str, currency_code: str) -> Account:
    """حساب فرعي مُخصَّص مسبقاً تحت أب مفرَّع لكل عملة (مثال: `4110`→`4111`).

    التخصيص نفسه (`account_number_counters`/`assignments`) بيانات تهيئة
    تُزرع في `app.cli.seed` — هذه الدالة قراءة فقط، لا تُنشئ تخصيصاً جديداً.
    """
    parent = get_account_by_code(db, parent_code)
    assignment = db.get(AccountNumberAssignment, (parent.id, currency_code))
    if assignment is None:
        raise AccountNotFoundError(
            f"لا تخصيص عملة {currency_code} تحت الحساب الأب {parent_code}"
        )
    return get_account_by_code(db, assignment.assigned_code)


def leaf_accounts(db: Session, *, include_client_accounts: bool = True) -> list[Account]:
    """حسابات قابلة للترحيل مباشرة — أوراق الشجرة النشطة فقط (لا رؤوس
    تجميع لها أبناء). `include_client_accounts=False` يستثني أيضاً
    حسابات العملاء المُشتقة (`2100-*`) — نفس نمط `/reference/accounts`
    وتصفية `account_filters.py`، مُشتَرَك هنا بدل تكراره حرفياً بكل شاشة
    جديدة تحتاجه (لوحة التحكم/مركز السيولة/الحسابات، §٧-٢·٧-٤·٧-٧)."""
    all_accounts = db.execute(select(Account).where(Account.is_active.is_(True))).scalars().all()
    parent_ids = {a.parent_id for a in all_accounts if a.parent_id is not None}
    return [
        a for a in all_accounts
        if a.id not in parent_ids and (include_client_accounts or a.client_id is None)
    ]


def get_or_create_client_account(
    db: Session, *, client: Client, currency_code: str, location_code: str
) -> Account:
    """§٣ (تعديل معتمد): `2100-{client.code}-{ccy}-{loc}` — توليد حتمي، إنشاء كسول.

    الإنشاء الكسول عرضة لسباق حقيقي: طلبان متزامنان لأول استخدام لنفس
    التركيبة قد يريا كلاهما "غير موجود" معاً فيحاولان الإدراج معاً وينتهك
    أحدهما قيد `UNIQUE(code)`. `pg_advisory_xact_lock` بمعرّف مُشتق من
    الكود نفسه يُسلسل كل الطلبات لنفس التركيبة قبل الفحص، بنفس أسلوب
    `idempotency.run` تماماً — يُطلَق تلقائياً عند نهاية معاملة المستدعي.
    """
    location = get_location_by_code(db, location_code)
    code = f"2100-{client.code}-{currency_code}-{location_code}"
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key)::bigint)"), {"key": code})

    existing = db.execute(select(Account).where(Account.code == code)).scalar_one_or_none()
    if existing is not None:
        return existing

    whitelisted = db.get(ClientCurrencyLocation, (currency_code, location.id))
    if whitelisted is None:
        raise InvalidClientLocationError(
            f"تركيبة {currency_code}·{location_code} غير مسموح بها لحسابات العملاء"
        )

    parent = get_account_by_code(db, "2100")
    account = Account(
        code=code,
        name_ar=f"{client.name_ar} · {currency_code} · {location.name_ar}",
        type=AccountType.LIABILITY,
        currency_code=currency_code,
        location_id=location.id,
        parent_id=parent.id,
        client_id=client.id,
        is_system=False,
        is_active=True,
    )
    db.add(account)
    db.flush()
    return account


def _assign_next_child_code(db: Session, parent: Account) -> str:
    """رقم فرعي تسلسلي جديد تحت `parent` — نفس آلية `account_number_counters`
    المستخدَمة في `app.cli.seed._subdivide_by_currency` بالضبط (الرقم
    الأخير من كود الأب يُستبدَل برقم تسلسلي، لا يُضاف)، لكن هنا **بلا**
    `account_number_assignments` (ذاك مفتاحه عملة واحدة لكل أب — لا يناسب
    "حساب واحد لكل شريك×عملة×موقع"؛ كل استدعاء هنا إنشاء متعمَّد جديد لا
    بحثاً كسولاً idempotent). قفل صفّي (`with_for_update`) يمنع تصادماً
    حقيقياً بين طلبين متزامنين على نفس الأب — نفس أسلوب `numbering.py`.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key)::bigint)"), {"key": f"account_child:{parent.id}"})
    counter = db.execute(
        select(AccountNumberCounter).where(AccountNumberCounter.parent_id == parent.id).with_for_update()
    ).scalar_one_or_none()
    if counter is None:
        counter = AccountNumberCounter(parent_id=parent.id, next_suffix=1)
        db.add(counter)
        db.flush()
    suffix = counter.next_suffix
    if suffix > 9 or not parent.code.endswith("0"):
        raise AccountNumberExhaustedError(
            f"لا مجال لحساب فرعي جديد تحت {parent.code} — الأرقام الفرعية (١-٩) استُهلكت بالكامل"
        )
    counter.next_suffix = suffix + 1
    return f"{parent.code[:-1]}{suffix}"


_PARTNER_ACCOUNT_PARENTS = {"1310", "1320"}  # مراسلو ليبيا · مراسلو تركيا


def create_partner_account(
    db: Session, *, partner_id: int, parent_code: str, currency_code: str, location_code: str, name_ar: str,
) -> Account:
    """حساب مالي حقيقي جديد لشريك (مراسل تحت ١٣١٠/١٣٢٠) — بترقيم آلي صحيح
    لا يدوي (`T-ACC-...` كان حصراً لبيانات الاختبار، انظر `tests/factories.py`).
    """
    if parent_code not in _PARTNER_ACCOUNT_PARENTS:
        raise AccountNotFoundError(f"{parent_code} ليس أباً صالحاً لحساب شريك — المسموح: {sorted(_PARTNER_ACCOUNT_PARENTS)}")
    parent = get_account_by_code(db, parent_code)
    location = get_location_by_code(db, location_code)
    code = _assign_next_child_code(db, parent)
    account = Account(
        code=code, name_ar=name_ar, type=parent.type, currency_code=currency_code, location_id=location.id,
        form=AccountForm.CORRESPONDENT, parent_id=parent.id, partner_id=partner_id, is_system=False, is_active=True,
    )
    db.add(account)
    db.flush()
    return account


def create_bank_account(
    db: Session, *, currency_code: str, location_code: str, name_ar: str, parent_code: str = "1400",
) -> Account:
    """حساب بنكي مملوك جديد (تحت ١٤٠٠) — لا شريك خارجي مرتبط به، بخلاف
    حسابات المراسلين. بترقيم آلي صحيح لا يدوي."""
    parent = get_account_by_code(db, parent_code)
    location = get_location_by_code(db, location_code)
    code = _assign_next_child_code(db, parent)
    account = Account(
        code=code, name_ar=name_ar, type=parent.type, currency_code=currency_code, location_id=location.id,
        form=AccountForm.BANK, parent_id=parent.id, is_system=False, is_active=True,
    )
    db.add(account)
    db.flush()
    return account
