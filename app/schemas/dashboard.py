"""مخطّطات ردود لوحة التحكم · مركز السيولة · الحسابات · الدفعات (§٧-٢،
٧-٤، ٧-٧، ٧-٨) — قراءة فقط، لا كتابة هنا.

**قرار تصميم مسجَّل عمداً**: أي مبلغ متعدد العملات (التزامات العملاء
الإجمالية، الربح الصافي) يُعرض **مُفكَّكاً لكل عملة على حدة**، لا رقماً
واحداً مُدمَجاً عبر تحويل عملة مُخترَع — لا سعر صرف "رسمي" واحد موثوق في
النظام يُبرِّر دمج دينار مع دولار مع رمبي في رقم واحد. هذا امتداد لنفس
مبدأ "الربحان لا يُدمجان إلا في سطر الصافي" الذي طلبتَه صراحة، مطبَّق على
كل مكان مشابه في هذه الشاشات.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from .reference import JournalEntryOut


class CurrencyAmount(BaseModel):
    currency_code: str
    amount: Decimal


class DashboardKpis(BaseModel):
    """كل عملة نشطة سطر مستقل — لا ثلاث بطاقات دينار/دولار/رمبي مُثبَّتة
    بالكود (اختبار القبول ٤٨: إضافة عملة رابعة تعمل بلا تغييرات كود؛
    لوحة تحكم تفترض ثلاثاً فقط تكسر هذا فعلياً حين تُضاف عملة)."""

    funds: list[CurrencyAmount]  # صناديق + مراسلون + بنوك (كل الأصول)، لكل عملة
    client_liabilities: list[CurrencyAmount]
    client_debts: list[CurrencyAmount]  # إجمالي ما يدين به العملاء لنا (أرصدتهم السالبة) لكل عملة — رؤية بلا سقف (٢٠٢٦-١٠-٠٣)


class ProfitBreakdown(BaseModel):
    """§٧-٢: مقسّمة حسب المصدر والعملة — فرق التحويل (CASH_TRANSFER→٤١١٠)
    وفروق صرافة العملاء (EXCHANGE بعميل/REMIT_OUT→٤١٢٠) دائماً منفصلتان،
    `net_by_currency` مجموعهما داخل كل عملة وحدها (لا دمج عبر العملات).
    صرافة الخزينة بلا ربح (سعر واحد — ٢٠٢٦-١٠-٠٢) فلا بند لها هنا."""

    transfer_fee: list[CurrencyAmount]
    exchange_spread: list[CurrencyAmount]
    net_by_currency: list[CurrencyAmount]
    # عمولة الصرافة (٢٠٢٦-١٠-٠٤): بند منفصل عن فرق السعر لكل عملة (موجب = إيراد نقبضه، سالب = مصروف ندفعه) — لا يدخل `net_by_currency`
    exchange_commission: list[CurrencyAmount] = []


class TopClientRow(BaseModel):
    client_id: int
    code: str
    name_ar: str
    # معيار الترتيب: عدد القيود المُرحَّلة (POSTED) التي شارك فيها العميل —
    # نشاط لا رصيد، تفادياً لدمج عملات مختلفة (دينار/دولار/رمبي) في رقم
    # واحد بلا سعر صرف موثوق.
    operation_count: int


class AlertRow(BaseModel):
    severity: str  # critical · warning · info
    code: str
    message_ar: str


class DashboardSummary(BaseModel):
    kpis: DashboardKpis
    today_profit: ProfitBreakdown
    top_clients: list[TopClientRow]
    recent_entries: list[JournalEntryOut]
    alerts: list[AlertRow]


class LiquidityRow(BaseModel):
    currency_code: str
    location_code: str
    location_name_ar: str
    assets: Decimal
    liabilities: Decimal
    net: Decimal


class AccountBalanceRow(BaseModel):
    code: str
    name_ar: str
    currency_code: str
    balance: Decimal


class CorrespondentGroup(BaseModel):
    partner_id: Optional[int] = None
    partner_name_ar: str
    accounts: list[AccountBalanceRow]


class CorrespondentsResponse(BaseModel):
    groups: list[CorrespondentGroup]
    totals: list[CurrencyAmount]


class BanksResponse(BaseModel):
    accounts: list[AccountBalanceRow]
    totals: list[CurrencyAmount]


class BoxesResponse(BaseModel):
    accounts: list[AccountBalanceRow]
    totals: list[CurrencyAmount]


class LotRow(BaseModel):
    id: int
    lot_no: str
    swift_external_ref: Optional[str] = None
    partner_name_ar: Optional[str] = None
    arrival_date: date
    original_qty: Decimal
    cost_rate: Decimal
    remaining_qty: Decimal
    num_sales: int
    weighted_avg_sale_rate: Optional[Decimal] = None
    total_profit: Decimal
    profit_currency: Optional[str] = None
    status: str


class LotConsumptionRow(BaseModel):
    consumed_at: datetime
    client_name_ar: Optional[str] = None
    qty: Decimal
    client_rate: Decimal
    cost_share: Decimal
    profit: Decimal
    profit_currency: str


class LotDetail(BaseModel):
    lot: LotRow
    consumptions: list[LotConsumptionRow]
