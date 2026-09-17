"""مخطّطات ردود بيانات مرجعية للواجهة — بحث/قوائم فقط، لا كتابة هنا."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class CurrencyOut(BaseModel):
    code: str
    name_ar: str
    symbol: str
    decimals: int
    is_pivot: bool


class LocationOut(BaseModel):
    code: str
    name_ar: str
    country: str


class ClientCurrencyLocationOut(BaseModel):
    currency_code: str
    location_code: str


class AccountOut(BaseModel):
    code: str
    name_ar: str
    type: str
    currency_code: Optional[str] = None
    location_code: Optional[str] = None
    form: Optional[str] = None


class ClientSearchResultOut(BaseModel):
    id: int
    code: str
    name_ar: str
    phone: Optional[str] = None
    credit_allowed: bool


class ClientBalanceOut(BaseModel):
    account_code: str
    currency_code: str
    location_code: Optional[str] = None
    balance: Decimal


class BeneficiaryOut(BaseModel):
    id: int
    name: str
    account_number: str
    bank_name: Optional[str] = None
    currency_code: str


class JournalLineOut(BaseModel):
    account_code: str
    account_name_ar: str
    currency_code: str
    debit: Decimal
    credit: Decimal
    memo: Optional[str] = None


class PendingSwiftMovementOut(BaseModel):
    """حركات سويفت `SENT` لم تُستقبَل ولم تُرتجَع بعد — ما يحتاجه اختيار
    SWIFT_IN/SWIFT_RETURN في الواجهة (§٤ رقم ٧/٨)."""

    id: int
    amount: Decimal
    currency_code: str
    transfer_date: date
    external_ref: Optional[str] = None
    partner_name_ar: Optional[str] = None
    out_entry_no: Optional[str] = None
    # الحساب المراسل الأصلي مُشتقّ من قيد الخروج — SWIFT_RETURN يستخدمه
    # آلياً بلا أي اختيار من المستخدم (خطر إرجاع المال لمراسل خاطئ).
    partner_account_code: Optional[str] = None


class JournalEntryOut(BaseModel):
    id: int
    entry_no: str
    entry_date: date
    operation_type: str
    status: str
    description: Optional[str] = None
    note: Optional[str] = None
    replaces_entry_id: Optional[int] = None
    client_id: Optional[int] = None
    client_name_ar: Optional[str] = None
    profit_amount: Optional[Decimal] = None
    profit_currency: Optional[str] = None
    chain_ref: Optional[str] = None
    lines: list[JournalLineOut]
