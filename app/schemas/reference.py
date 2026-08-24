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


class JournalEntryOut(BaseModel):
    id: int
    entry_no: str
    entry_date: date
    operation_type: str
    status: str
    description: Optional[str] = None
    client_name_ar: Optional[str] = None
    profit_amount: Optional[Decimal] = None
    profit_currency: Optional[str] = None
    chain_ref: Optional[str] = None
    lines: list[JournalLineOut]
