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


class BackdateFields(BaseModel):
    """تاريخ العملية (٢٠٢٦-٠٩-٢٢، طلب مالك) — مشترك بين كل العمليات ما عدا
    OPENING (لها `as_of_date` الخاص بها أصلاً بنفس الدور). `None` = اليوم
    بتوقيت العمل (`app.engine.clock.local_entry_date`). البوابة الفعلية
    (فترة تأسيسية مفتوحة = حرّية كاملة؛ فترة شهرية مقفلة = مدير + سبب
    إلزامي) قائمة بالفعل في `posting._check_backdate_gate` — هذا الحقل
    فقط يمرِّر اختيار المستخدم إليها، لا منطق تحقق جديد هنا."""
    entry_date: Optional[date] = None
    backdate_reason: Optional[str] = None


class ReceiptRequest(BackdateFields):
    client_id: int
    currency_code: str
    location_code: str
    amount: Decimal = Field(gt=0)
    receiving_account_code: str
    payment_method: Optional[str] = None
    description: Optional[str] = None
    note: Optional[str] = None  # ملاحظة وقت الإدخال — تظهر في الإيصال/كشف الحساب، بخلاف description


class PaymentRequest(BackdateFields):
    client_id: int
    currency_code: str
    location_code: str
    amount: Decimal = Field(gt=0)
    paying_account_code: str
    description: Optional[str] = None
    note: Optional[str] = None
    allow_negative: bool = False
    override_reason: Optional[str] = None


_TREASURY_NO_COST_MESSAGE = (
    "صرافة الخزينة بسعر واحد هو السعر المنفَّذ فعلاً (client_rate) — لا cost_rate "
    "ولا negative_margin_reason: لا ربح ولا خسارة في العملية نفسها"
)


class ExchangeRatesRequest(BackdateFields):
    """نطاقان حصرياً — أحدهما، لا كلاهما ولا أيّ منهما (٢٠٢٦-٠٩-٢٤):
    **عميل** (`client_id`+موقعا من/إلى، سعران: `cost_rate` و`client_rate`) أو
    **خزينة** (`source_account_code`+`destination_account_code`، لا حساب عميل
    في القيد إطلاقاً).

    ٢٠٢٦-١٠-٠٢ (طلب مالك): نطاق الخزينة **سعر واحد فقط** — `client_rate` هو
    السعر المنفَّذ فعلاً (الاسم تاريخي، يطابق عمود `journal_entries.client_rate`)،
    و`cost_rate`/`negative_margin_reason` ممنوعان فيه (٤٢٢)."""
    client_id: Optional[int] = None
    from_location_code: Optional[str] = None
    to_location_code: Optional[str] = None
    source_account_code: Optional[str] = None
    destination_account_code: Optional[str] = None
    from_currency: str
    to_currency: str
    amount: Decimal = Field(gt=0)
    cost_rate: Optional[Decimal] = Field(default=None, gt=0)  # نطاق العميل فقط
    client_rate: Decimal = Field(gt=0)
    description: Optional[str] = None
    note: Optional[str] = None
    negative_margin_reason: Optional[str] = None

    @model_validator(mode="after")
    def _one_scope(self):
        is_client = self.client_id is not None
        is_treasury = self.source_account_code is not None or self.destination_account_code is not None
        if is_client == is_treasury:
            raise ValueError(
                "مرّر (client_id + from_location_code + to_location_code) لصرافة عميل، أو "
                "(source_account_code + destination_account_code) لصرافة خزينة — لا كليهما ولا أياً منهما"
            )
        if is_client and not (self.from_location_code and self.to_location_code):
            raise ValueError("صرافة عميل تتطلب from_location_code وto_location_code")
        if is_treasury and not (self.source_account_code and self.destination_account_code):
            raise ValueError("صرافة خزينة تتطلب source_account_code وdestination_account_code معاً")
        if is_client and self.cost_rate is None:
            raise ValueError("صرافة عميل تتطلب cost_rate (سعر التكلفة)")
        if is_treasury and (self.cost_rate is not None or self.negative_margin_reason is not None):
            raise ValueError(_TREASURY_NO_COST_MESSAGE)
        return self


class ExchangeLotRequest(BackdateFields):
    client_id: int
    from_location_code: str
    to_location_code: str
    amount: Decimal = Field(gt=0)  # بالدولار
    client_rate: Decimal = Field(gt=0)
    description: Optional[str] = None
    note: Optional[str] = None


class ExchangeChainStep1(BaseModel):
    """موقعا من/إلى لصرافة عميل، أو حسابا مصدر/وجهة لصرافة خزينة — يحسمه
    `ExchangeChainRequest.client_id` (موجود=عميل، غائب=خزينة)."""
    from_currency: str
    to_currency: str
    amount: Decimal = Field(gt=0)
    cost_rate: Optional[Decimal] = Field(default=None, gt=0)  # نطاق العميل فقط
    client_rate: Decimal = Field(gt=0)
    negative_margin_reason: Optional[str] = None
    from_location_code: Optional[str] = None
    to_location_code: Optional[str] = None
    source_account_code: Optional[str] = None
    destination_account_code: Optional[str] = None


class ExchangeChainStep2(BaseModel):
    """لا `source_account_code`/موقع "من" هنا — الخطوة ٢ تنطلق دائماً من
    حيث انتهت الخطوة ١ (وجهتها، بالمبلغ الفعلي المُرحَّل هناك)."""
    to_currency: str
    cost_rate: Optional[Decimal] = Field(default=None, gt=0)  # نطاق العميل فقط
    client_rate: Decimal = Field(gt=0)
    negative_margin_reason: Optional[str] = None
    to_location_code: Optional[str] = None
    destination_account_code: Optional[str] = None


class ExchangeChainRequest(BackdateFields):
    """نطاقان (٢٠٢٦-٠٩-٢٤): `client_id` موجود = سلسلة عميل (مواقع الخطوتين
    إلزامية)، غائب = سلسلة خزينة (حسابا مصدر/وجهة الخطوة ١ + حساب وجهة
    الخطوة ٢ إلزامية، لا عميل في أي قيد)."""
    client_id: Optional[int] = None
    step1: ExchangeChainStep1
    step2: ExchangeChainStep2
    description: Optional[str] = None
    note: Optional[str] = None  # يُنسَخ لكلا قيدي الخطوتين

    @model_validator(mode="after")
    def _one_scope(self):
        if self.client_id is None:
            if not (self.step1.source_account_code and self.step1.destination_account_code):
                raise ValueError("سلسلة صرافة خزينة تتطلب step1.source_account_code وstep1.destination_account_code")
            if not self.step2.destination_account_code:
                raise ValueError("سلسلة صرافة خزينة تتطلب step2.destination_account_code")
            for step in (self.step1, self.step2):
                if step.cost_rate is not None or step.negative_margin_reason is not None:
                    raise ValueError(_TREASURY_NO_COST_MESSAGE)
        else:
            if not (self.step1.from_location_code and self.step1.to_location_code):
                raise ValueError("سلسلة صرافة عميل تتطلب step1.from_location_code وstep1.to_location_code")
            if not self.step2.to_location_code:
                raise ValueError("سلسلة صرافة عميل تتطلب step2.to_location_code")
            if self.step1.cost_rate is None or self.step2.cost_rate is None:
                raise ValueError("سلسلة صرافة عميل تتطلب cost_rate في الخطوتين")
        return self


class ExchangeChainResponse(BaseModel):
    chain_ref: str
    step1: EntryResponse
    step2: EntryResponse


class CashTransferRequest(BackdateFields):
    client_id: int
    currency_code: str
    from_location_code: str
    to_location_code: str
    amount: Decimal = Field(gt=0)
    source_account_code: str
    execution_account_code: str
    # None = يُخصَم من رصيد العميل نفسه بعملة العمولة (الافتراضي —
    # collection_location_code أو from_location_code إن غاب) — لا حساب
    # شركة صريح. انظر التوثيق الكامل في app/engine/operations/cash_transfer.py.
    collection_account_code: Optional[str] = None
    collection_location_code: Optional[str] = None
    commission_currency: str
    client_commission_amount: Decimal = Field(ge=0)
    cost_commission_amount: Decimal = Field(ge=0)
    cost_correspondent_account_code: str
    description: Optional[str] = None
    note: Optional[str] = None
    allow_negative: bool = False
    override_reason: Optional[str] = None


class LocalMoveRequest(BackdateFields):
    currency_code: str
    from_account_code: str
    to_account_code: str
    amount: Decimal = Field(gt=0)
    fee_amount: Decimal = Field(default=Decimal("0"), ge=0)
    description: Optional[str] = None
    note: Optional[str] = None
    allow_negative: bool = False
    override_reason: Optional[str] = None


class RemitOutRequest(BackdateFields):
    client_id: int
    from_location_code: str  # موقع حساب العميل المخصوم منه
    sending_account_code: str  # حساب الشركة المُرسِل: بنك/مراسل/صندوق **بالعملة نفسها** (٢٠٢٦-١٠-٠٤: لا سعر ولا دولار وسيط)
    currency_code: str
    amount: Decimal = Field(gt=0)
    description: Optional[str] = None
    note: Optional[str] = None  # اسم التاجر ورقم حسابه (لا سجل مستفيدين)
    allow_negative: bool = False
    override_reason: Optional[str] = None


class SwiftOutRequest(BackdateFields):
    partner_account_code: str
    amount: Decimal = Field(gt=0)
    external_ref: Optional[str] = None
    description: Optional[str] = None
    note: Optional[str] = None
    allow_negative: bool = False
    override_reason: Optional[str] = None


class SwiftInRequest(BackdateFields):
    swift_movement_id: int
    total_amount: Decimal = Field(gt=0)
    fee_amount: Decimal = Field(ge=0)
    receiving_account_code: str
    bank_conversion_rate: Optional[Decimal] = Field(default=None, gt=0)
    description: Optional[str] = None
    note: Optional[str] = None


class SwiftReturnRequest(BackdateFields):
    swift_movement_id: int
    partner_account_code: str
    total_amount: Decimal = Field(gt=0)
    client_id: int
    client_location_code: str
    return_fee_amount: Decimal = Field(default=Decimal("0"), ge=0)
    description: Optional[str] = None
    note: Optional[str] = None


class ExpenseRequest(BackdateFields):
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


class AdjustmentRequest(BackdateFields):
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
