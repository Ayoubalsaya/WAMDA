"""مخطّطات طلبات/ردود الاثنتي عشرة عملية (§٤) — القسم ب/ج من مواصفة التصميم.

كل الحقول التي يشتقها المحرك (chain_ref · profit_amount · entry_no ...)
غائبة عمداً عن الطلبات — تُعرض في الرد فقط (هـ-٤: "أي حقل مشتق لا يقبل
الإدخال"). `idempotency_key` ليس حقلاً هنا — يصل عبر ترويسة `Idempotency-Key`
(§٦-٤)، لا في جسم الطلب.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import ConfidenceLevel, OpeningSourceType


class EntryResponse(BaseModel):
    id: int
    entry_no: str
    status: str
    profit_amount: Optional[Decimal] = None
    profit_currency: Optional[str] = None
    chain_ref: Optional[str] = None
    chain_seq: Optional[int] = None
    chain_total: Optional[int] = None


class ReceiptRequest(BaseModel):
    client_id: int
    currency_code: str
    location_code: str
    amount: Decimal = Field(gt=0)
    receiving_account_code: str
    payment_method: Optional[str] = None
    description: Optional[str] = None


class PaymentRequest(BaseModel):
    client_id: int
    currency_code: str
    location_code: str
    amount: Decimal = Field(gt=0)
    paying_account_code: str
    description: Optional[str] = None
    allow_negative: bool = False
    override_reason: Optional[str] = None


class ExchangeRatesRequest(BaseModel):
    client_id: int
    from_currency: str
    from_location_code: str
    to_currency: str
    to_location_code: str
    amount: Decimal = Field(gt=0)
    cost_rate: Decimal = Field(gt=0)
    client_rate: Decimal = Field(gt=0)
    description: Optional[str] = None
    negative_margin_reason: Optional[str] = None


class ExchangeLotRequest(BaseModel):
    client_id: int
    from_location_code: str
    to_location_code: str
    amount: Decimal = Field(gt=0)  # بالدولار
    client_rate: Decimal = Field(gt=0)
    description: Optional[str] = None


class ExchangeChainStep1(BaseModel):
    from_currency: str
    from_location_code: str
    to_currency: str
    to_location_code: str
    amount: Decimal = Field(gt=0)
    cost_rate: Decimal = Field(gt=0)
    client_rate: Decimal = Field(gt=0)
    negative_margin_reason: Optional[str] = None


class ExchangeChainStep2(BaseModel):
    to_currency: str
    to_location_code: str
    cost_rate: Decimal = Field(gt=0)
    client_rate: Decimal = Field(gt=0)
    negative_margin_reason: Optional[str] = None


class ExchangeChainRequest(BaseModel):
    client_id: int
    step1: ExchangeChainStep1
    step2: ExchangeChainStep2
    description: Optional[str] = None


class ExchangeChainResponse(BaseModel):
    chain_ref: str
    step1: EntryResponse
    step2: EntryResponse


class CashTransferRequest(BaseModel):
    client_id: int
    currency_code: str
    from_location_code: str
    to_location_code: str
    amount: Decimal = Field(gt=0)
    source_account_code: str
    execution_account_code: str
    collection_account_code: str
    commission_currency: str
    client_commission_amount: Decimal = Field(ge=0)
    cost_commission_amount: Decimal = Field(ge=0)
    cost_correspondent_account_code: str
    description: Optional[str] = None


class LocalMoveRequest(BaseModel):
    currency_code: str
    from_account_code: str
    to_account_code: str
    amount: Decimal = Field(gt=0)
    fee_amount: Decimal = Field(default=Decimal("0"), ge=0)
    description: Optional[str] = None


class RemitOutRequest(BaseModel):
    client_id: int
    from_location_code: str
    partner_account_code: str
    beneficiary_id: int
    beneficiary_amount: Decimal = Field(gt=0)
    cost_rate: Decimal = Field(gt=0)
    client_rate: Decimal = Field(gt=0)
    purpose: Optional[str] = None
    description: Optional[str] = None
    negative_margin_reason: Optional[str] = None


class SwiftOutRequest(BaseModel):
    partner_account_code: str
    amount: Decimal = Field(gt=0)
    external_ref: Optional[str] = None
    description: Optional[str] = None


class SwiftInRequest(BaseModel):
    swift_movement_id: int
    total_amount: Decimal = Field(gt=0)
    fee_amount: Decimal = Field(ge=0)
    receiving_account_code: str
    bank_conversion_rate: Optional[Decimal] = Field(default=None, gt=0)
    description: Optional[str] = None


class SwiftReturnRequest(BaseModel):
    swift_movement_id: int
    partner_account_code: str
    total_amount: Decimal = Field(gt=0)
    client_id: int
    client_location_code: str
    return_fee_amount: Decimal = Field(default=Decimal("0"), ge=0)
    description: Optional[str] = None


class ExpenseRequest(BaseModel):
    expense_account_code: str
    currency_code: str
    paying_account_code: str
    amount: Decimal = Field(gt=0)
    description: str
    allow_negative: bool = False
    override_reason: Optional[str] = None


class OpeningRequest(BaseModel):
    account_code: str
    currency_code: str
    amount: Decimal = Field(gt=0)
    is_debit: bool
    as_of_date: date
    source_type: OpeningSourceType
    confidence: ConfidenceLevel
    source_note: Optional[str] = None


class AdjustmentRequest(BaseModel):
    account_code: str
    currency_code: str
    amount: Decimal = Field(gt=0)
    is_debit: bool
    reason: str
    allow_negative: bool = False
