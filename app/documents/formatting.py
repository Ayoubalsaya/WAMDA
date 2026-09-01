"""تنسيق أرقام/عملات مشترَك لقوالب المستندات — نفس مبدأ
`frontend/src/lib/formatAmount.ts` (عدد منازل عملة الرقم الفعلي لا دقة
الرد الخام)، هنا على السيرفر وقت التوليد بدل المتصفح."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.models import Currency


def currency_decimals_map(db: OrmSession) -> dict[str, int]:
    rows = db.execute(select(Currency.code, Currency.decimals)).all()
    return {code: decimals for code, decimals in rows}


def format_amount(value: Optional[Decimal], currency_code: Optional[str], decimals_map: dict[str, int]) -> str:
    if value is None:
        return "—"
    decimals = decimals_map.get(currency_code, 2) if currency_code else 2
    return f"{value:.{decimals}f}"
