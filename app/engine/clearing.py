"""§٢-٣ — مقاصة الصرف: حساب `1900` مفرَّع لكل عملة (`1901`/`1902`/`1903`…).

كل عملية صرف تمرّ عبره فتتوازن كل عملة داخل نفسها بلا حاجة لعملة أساس
أو جدول أسعار يومي. رصيد المقاصة = المركز المكشوف بالتكلفة (تقرير السيولة).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.engine.accounts_repo import get_currency_subaccount
from app.models import Account

_CLEARING_PARENT_CODE = "1900"


def clearing_account(db: Session, currency_code: str) -> Account:
    return get_currency_subaccount(db, _CLEARING_PARENT_CODE, currency_code)
