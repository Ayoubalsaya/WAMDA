"""مخطّطات طلبات/ردود الاثنتي عشرة عملية (§٤) — القسم ب/ج من مواصفة التصميم.

كل الحقول التي يشتقها المحرك (chain_ref · profit_amount · entry_no ...)
غائبة عمداً عن الطلبات — تُعرض في الرد فقط (هـ-٤: "أي حقل مشتق لا يقبل
الإدخال"). `idempotency_key` ليس حقلاً هنا — يصل عبر ترويسة `Idempotency-Key`
(§٦-٤)، لا في جسم الطلب.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, model_validator

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
    # لقطة وجهة REMIT_OUT فقط — §3-3، تظهر في الإيصال ولا تتأثر بتعديل المستفيد لاحقاً
    beneficiary_name_snapshot: Optional[str] = None
    account_number_snapshot: Optional[str] = None
    bank_name_snapshot: Optional[str] = None


class ReceiptRequest(BaseModel):
    client_id: int
    currency_code: str
    location_code: str
    amount: Decimal = Field(gt=0)
    receiving_account_code: str
    payment_method: Optional[str] = None
    description: Optional[str] = None
    note: Optional[str] = None  # ملاحظة وقت الإدخال — تظهر في الإيصال/كشف الحساب، بخلاف description


class PaymentRequest(BaseModel):
    client_id: int
    currency_code: str
    location_code: str
    amount: Decimal = Field(gt=0)
    paying_account_code: str
    description: Optional[str] = None
    note: Optional[str] = None
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
    note: Optional[str] = None
    negative_margin_reason: Optional[str] = None


class ExchangeLotRequest(BaseModel):
    client_id: int
    from_location_code: str
    to_location_code: str
    amount: Decimal = Field(gt=0)  # بالدولار
    client_rate: Decimal = Field(gt=0)
    description: Optional[str] = None
    note: Optional[str] = None


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
    note: Optional[str] = None  # يُنسَخ لكلا قيدي الخطوتين


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
    note: Optional[str] = None


class LocalMoveRequest(BaseModel):
    currency_code: str
    from_account_code: str
    to_account_code: str
    amount: Decimal = Field(gt=0)
    fee_amount: Decimal = Field(default=Decimal("0"), ge=0)
    description: Optional[str] = None
    note: Optional[str] = None


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
    note: Optional[str] = None
    negative_margin_reason: Optional[str] = None


class SwiftOutRequest(BaseModel):
    partner_account_code: str
    amount: Decimal = Field(gt=0)
    external_ref: Optional[str] = None
    description: Optional[str] = None
    note: Optional[str] = None


class SwiftInRequest(BaseModel):
    swift_movement_id: int
    total_amount: Decimal = Field(gt=0)
    fee_amount: Decimal = Field(ge=0)
    receiving_account_code: str
    bank_conversion_rate: Optional[Decimal] = Field(default=None, gt=0)
    description: Optional[str] = None
    note: Optional[str] = None


class SwiftReturnRequest(BaseModel):
    swift_movement_id: int
    partner_account_code: str
    total_amount: Decimal = Field(gt=0)
    client_id: int
    client_location_code: str
    return_fee_amount: Decimal = Field(default=Decimal("0"), ge=0)
    description: Optional[str] = None
    note: Optional[str] = None


class ExpenseRequest(BaseModel):
    expense_account_code: str
    currency_code: str
    paying_account_code: str
    amount: Decimal = Field(gt=0)
    description: str
    note: Optional[str] = None
    allow_negative: bool = False
    override_reason: Optional[str] = None


class OpeningRequest(BaseModel):
    """رصيد افتتاحي — إمّا لحساب نظامي (`account_code`) أو لحساب عميل
    (`client_id` + `location_code`، يُنشَأ كسولاً إن لم يوجد). أحدهما
    فقط، لا كلاهما."""
    account_code: Optional[str] = None
    client_id: Optional[int] = None
    location_code: Optional[str] = None
    currency_code: str
    amount: Decimal = Field(gt=0)
    is_debit: bool
    as_of_date: date
    source_type: OpeningSourceType
    confidence: ConfidenceLevel
    source_note: Optional[str] = None
    note: Optional[str] = None

    @model_validator(mode="after")
    def _one_target(self):
        if bool(self.account_code) == bool(self.client_id):
            raise ValueError("مرّر account_code أو client_id (مع location_code)، لا كليهما ولا أياً منهما")
        if self.client_id and not self.location_code:
            raise ValueError("رصيد افتتاحي لعميل يتطلب location_code")
        return self


class AdjustmentRequest(BaseModel):
    account_code: str
    currency_code: str
    amount: Decimal = Field(gt=0)
    is_debit: bool
    reason: str
    note: Optional[str] = None
    allow_negative: bool = False


class CommentCreate(BaseModel):
    body: str = Field(min_length=1)


class CommentOut(BaseModel):
    id: int
    entry_id: int
    body: str
    created_by: int
    created_by_name: str
    created_at: datetime


class CancelRequest(BaseModel):
    reason: str = Field(min_length=1)


class CancelResponse(BaseModel):
    cancelled_entry_ids: list[int]
    chain_cascade: bool


class EditRequest(BaseModel):
    """طلب تعديل عام لأي عملية — عكس الأصل + إنشاء بديل بنفس نوع العملية
    بقيم جديدة، ذرّياً. `operation` نفس بنية طلب الإنشاء الأصلي لذلك النوع
    (§٤) بحقل إضافي `reason` إلزامي؛ يُوجَّه داخلياً لنفس دالة `operations/*`
    المستخدَمة عند الإنشاء الأول — لا منطق محاسبي مكرَّر هنا."""
    reason: str = Field(min_length=1)
    operation: dict


class EditResponse(BaseModel):
    reversed_entry_id: int
    new_entry: EntryResponse


class HistoryStep(BaseModel):
    entry_id: int
    entry_no: str
    kind: str  # original | reversal | replacement
    status: str
    created_by_name: str
    created_at: datetime
    reason: Optional[str] = None


class HistoryResponse(BaseModel):
    steps: list[HistoryStep]
