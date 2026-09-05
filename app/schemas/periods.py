"""مخطّطات إقفال الفترات (§٩ المرحلة ١١)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class PeriodRow(BaseModel):
    year: int
    month: int
    is_closed: bool
    closed_by_username: Optional[str] = None
    closed_at: Optional[datetime] = None


class ClosePeriodRequest(BaseModel):
    year: int
    month: int


class ReopenPeriodRequest(BaseModel):
    year: int
    month: int


class FoundingPeriodStatus(BaseModel):
    is_open: bool
    closed_at: Optional[datetime] = None
    closed_by_username: Optional[str] = None
    suspense_balance_by_currency: dict[str, str]


class CloseFoundingPeriodRequest(BaseModel):
    acknowledged_remaining_suspense: bool = False


class OpeningBalanceRow(BaseModel):
    """سطر رصيد افتتاحي مُدخَل — لمراجعة التشغيل المتوازي (المرحلة ١٤)."""
    id: int
    account_code: str
    account_name_ar: str
    currency_code: str
    amount: str
    as_of_date: date
    source_type: str      # VERIFIED · RECONSTRUCTED · KNOWN_BALANCE · ADJUSTMENT
    confidence: str        # HIGH · MEDIUM · LOW
    source_note: Optional[str] = None
    contra_account_code: str  # ٣١٠٠.x (ثقة عالية) أو ٣٩٠٠.x (فروق تأسيسية)
    approved_by_username: Optional[str] = None
