"""§٢-١٠ — اشتقاق الطرف المقابل للرصيد الافتتاحي من درجة الثقة.

confidence = HIGH            → الطرف المقابل 3100 رأس المال (فرعي العملة)
confidence = MEDIUM أو LOW    → الطرف المقابل 3900 فروق تأسيسية (فرعي العملة)
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.engine.accounts_repo import get_currency_subaccount
from app.models import Account
from app.models.enums import ConfidenceLevel


def derive_contra_account(db: Session, *, confidence: ConfidenceLevel, currency_code: str) -> Account:
    parent_code = "3100" if confidence == ConfidenceLevel.HIGH else "3900"
    return get_currency_subaccount(db, parent_code, currency_code)
