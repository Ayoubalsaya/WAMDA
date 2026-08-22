"""بحث/اشتقاق الحسابات — النظامية منها وحسابات العملاء المُشتقة حتمياً.

لا منطق محاسبي هنا، مجرد بحث/إنشاء كسول. المنطق المحاسبي في posting.py
ووحدات operations/.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, AccountNumberAssignment, Client, Currency, Location
from app.models.enums import AccountType


class AccountNotFoundError(Exception):
    pass


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


def get_or_create_client_account(
    db: Session, *, client: Client, currency_code: str, location_code: str
) -> Account:
    """§٣ (تعديل معتمد): `2100-{client.code}-{ccy}-{loc}` — توليد حتمي، إنشاء كسول."""
    location = get_location_by_code(db, location_code)
    code = f"2100-{client.code}-{currency_code}-{location_code}"
    existing = db.execute(select(Account).where(Account.code == code)).scalar_one_or_none()
    if existing is not None:
        return existing

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
