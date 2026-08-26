"""مخطّطات شاشات العملاء (§٧-٥) — قائمة · صفحة عميل · كشف حساب · مستفيدون.

لا `cost_rate` في أي مخطّط هنا — هذه شاشات قد يراها العميل نفسه لاحقاً
(كشف حساب يُطبَع/يُشارَك)، والقاعدة (و-١) لا استثناء فيها لواجهة الموظف.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class CreditLimitOut(BaseModel):
    currency_code: str
    limit_amount: Decimal


class ClientBalanceRow(BaseModel):
    currency_code: str
    location_code: Optional[str] = None
    account_code: str
    balance: Decimal


class ClientListRow(BaseModel):
    id: int
    code: str
    name_ar: str
    phone: Optional[str] = None
    credit_allowed: bool
    is_active: bool
    balances: list[ClientBalanceRow]
    credit_limits: list[CreditLimitOut]
    last_activity: Optional[date] = None


class ClientDetail(BaseModel):
    id: int
    code: str
    name_ar: str
    name_en: Optional[str] = None
    phone: Optional[str] = None
    id_number: Optional[str] = None
    credit_allowed: bool
    is_active: bool
    created_at: datetime
    balances: list[ClientBalanceRow]
    credit_limits: list[CreditLimitOut]


class CreateClientRequest(BaseModel):
    code: str = Field(min_length=1)
    name_ar: str = Field(min_length=1)
    name_en: Optional[str] = None
    phone: Optional[str] = None
    id_number: Optional[str] = None


class UpdateClientRequest(BaseModel):
    name_ar: Optional[str] = Field(default=None, min_length=1)
    name_en: Optional[str] = None
    phone: Optional[str] = None
    id_number: Optional[str] = None


class SetCreditAllowedRequest(BaseModel):
    credit_allowed: bool


class SetCreditLimitRequest(BaseModel):
    limit_amount: Decimal = Field(ge=0)


class StatementRow(BaseModel):
    entry_id: int
    entry_no: str
    entry_date: date
    operation_type: str
    description: Optional[str] = None
    debit: Decimal
    credit: Decimal
    running_balance: Decimal


class StatementResponse(BaseModel):
    account_code: str
    currency_code: str
    location_code: str
    opening_balance: Decimal
    closing_balance: Decimal
    rows: list[StatementRow]


class CreateBeneficiaryRequest(BaseModel):
    name: str = Field(min_length=1)
    account_number: str = Field(min_length=1)
    bank_name: Optional[str] = None
    currency_code: str
    purpose: Optional[str] = None
    notes: Optional[str] = None


class BeneficiaryDetail(BaseModel):
    id: int
    name: str
    account_number: str
    bank_name: Optional[str] = None
    currency_code: str
    purpose: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool


class SetBeneficiaryActiveRequest(BaseModel):
    is_active: bool
