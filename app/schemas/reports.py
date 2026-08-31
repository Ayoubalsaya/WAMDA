"""مخطّطات التقارير (§٧-١١) — قراءة فقط.

**نفس قاعدة لوحة التحكم (المرحلة ٨) بلا استثناء**: أي مبلغ متعدد العملات
يُعرض مُفكَّكاً لكل عملة على حدة — لا دمج عبر تحويل عملة مُخترَع في أي
تقرير هنا.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.schemas.dashboard import CurrencyAmount

__all__ = ["CurrencyAmount"]


class DebtsByCurrencyRow(BaseModel):
    currency_code: str
    total_owed: Decimal
    client_count: int


class ProfitByPeriodRow(BaseModel):
    period_label: str  # "2026-W25" · "2026-06" · "2026"
    transfer_fee: list[CurrencyAmount]
    exchange_spread: list[CurrencyAmount]
    net_by_currency: list[CurrencyAmount]


class TrialBalanceRow(BaseModel):
    account_code: str
    account_name_ar: str
    account_type: str
    currency_code: Optional[str] = None
    debit: Decimal
    credit: Decimal


class TrialBalanceResponse(BaseModel):
    rows: list[TrialBalanceRow]
    total_debit_by_currency: list[CurrencyAmount]
    total_credit_by_currency: list[CurrencyAmount]
    balanced: bool  # صحّة رياضية — كل عملة توازن دائماً (§٢-٣)، فحص لا افتراض


class IncomeStatementLine(BaseModel):
    account_code: str
    account_name_ar: str
    currency_code: str
    amount: Decimal


class IncomeStatementResponse(BaseModel):
    revenue: list[IncomeStatementLine]
    expense: list[IncomeStatementLine]
    net_by_currency: list[CurrencyAmount]


class ClientProfitabilityRow(BaseModel):
    client_id: int
    client_code: str
    client_name_ar: str
    profit_by_currency: list[CurrencyAmount]
    operation_count: int


class ActivityRow(BaseModel):
    key: str  # عملة أو شهر YYYY-MM
    entry_count: int


class CorrespondentActivityRow(BaseModel):
    partner_id: int
    partner_name_ar: str
    entry_count: int
    total_debit_by_currency: list[CurrencyAmount]
    total_credit_by_currency: list[CurrencyAmount]


class SwiftHistoryRow(BaseModel):
    id: int
    status: str
    amount: Decimal
    currency_code: str
    transfer_date: date
    received_date: Optional[date] = None
    external_ref: Optional[str] = None
    partner_name_ar: Optional[str] = None


class LossMakingEntryRow(BaseModel):
    entry_id: int
    entry_no: str
    entry_date: date
    operation_type: str
    client_name_ar: Optional[str] = None
    profit_amount: Decimal
    profit_currency: str


class BalanceOverrideRow(BaseModel):
    id: int
    created_at: datetime
    action: str  # CREDIT_LIMIT_OVERRIDE · NEGATIVE_BALANCE_OVERRIDE
    account_code: Optional[str] = None
    entry_no: Optional[str] = None
    reason: Optional[str] = None
    actor_username: Optional[str] = None


class EmergencyEntryRow(BaseModel):
    entry_id: int
    entry_no: str
    entry_date: date
    operation_type: str
    real_operation_time: Optional[datetime] = None
    backdate_reason: Optional[str] = None


class FoundingReconciliationResponse(BaseModel):
    suspense_balance_by_currency: list[CurrencyAmount]  # رصيد ٣٩٠٠
    opening_balances_total_by_currency: list[CurrencyAmount]
    opening_balances_count: int
    open_reconciliation_items: int
