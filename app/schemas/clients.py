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
    """وضع ائتمان عملة: NONE · LIMIT (+ limit_amount) · UNLIMITED — يُرجَع لكل عملة فعّالة (غياب الصف = NONE)."""
    currency_code: str
    mode: str
    limit_amount: Optional[Decimal] = None


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
    credit_status: str  # OPEN · STOPPED · PARTIAL (محسوبة)
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
    credit_status: str
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


class SetCreditModeRequest(BaseModel):
    """زر العدسة: ضغطة واحدة لكل العملات — UNLIMITED (السماح بائتمان بلا سقف) أو NONE (إيقاف الائتمان)."""
    mode: str = Field(pattern="^(UNLIMITED|NONE)$")


class CreditModeChangeOut(BaseModel):
    credit_status: str
    outstanding_debts: list[ClientBalanceRow] = []  # عند الإيقاف: ديون قائمة (تحذير لا رفض)
    credit_limits: list[CreditLimitOut]


class SetCreditLimitRequest(BaseModel):
    """شاشة العميل: لكل عملة على حدة — بلا ائتمان · حد بمبلغ · بلا سقف."""
    mode: str = Field(default="LIMIT", pattern="^(NONE|LIMIT|UNLIMITED)$")
    limit_amount: Optional[Decimal] = Field(default=None, ge=0)


class StatementRow(BaseModel):
    entry_id: int
    entry_no: str
    entry_date: date
    operation_type: str
    description: Optional[str] = None
    debit: Decimal
    credit: Decimal
    running_balance: Decimal
    status: str
    note: Optional[str] = None
    replaces_entry_id: Optional[int] = None
    client_rate: Optional[str] = None
    chain_ref: Optional[str] = None


class StatementResponse(BaseModel):
    account_code: str
    currency_code: str
    location_code: str
    opening_balance: Decimal
    closing_balance: Decimal
    rows: list[StatementRow]


