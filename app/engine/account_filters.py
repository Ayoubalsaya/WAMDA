"""تصفية الحسابات حسب سياق العملية — بُعدان: (نوع العملية × دور الحقل)،
والعملة/الموقع تُطبَّقان فوقهما دائماً. هدف واحد: كل حقل اختيار حساب في
الواجهة يعرض ما يُتوقَّع استخدامه لهذه العملية تحديداً، لا شجرة الحسابات
كاملة ولا حتى كل حسابات تلك العملة.

**استثناءان مقصودان لا يمرّان عبر هذا الملف إطلاقاً**: OPENING وADJUSTMENT
تُظهران كل الحسابات القابلة للترحيل بلا تصفية — تسوية أو رصيد افتتاحي قد
يمسّان أي حساب في الشجرة، فتضييق الاختيار هنا كان سيمنع حالات مشروعة لا
يمكن حصرها مسبقاً. الواجهة تستدعي `/reference/accounts` غير المُصفّى لهما
كما كانت، مع تعليق صريح في `OperationForm.tsx` عند نقطة الاستخدام.

SWIFT_RETURN لا يظهر هنا أيضاً — لا حقل اختيار حساب له إطلاقاً؛ حساب
المراسل يُشتق آلياً من حركة السويفت المختارة (انظر `partner_account_code`
في `PendingSwiftMovementOut`)، لا يُعرض للمستخدم كخيار مطلقاً تفادياً
لخطر إرجاع المال لمراسل خاطئ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Location
from app.models.enums import AccountForm, AccountType


class InvalidAccountFieldError(Exception):
    """تركيبة (نوع عملية × حقل) غير معروفة — خطأ برمجي في المستدعي، لا حالة بيانات."""


class LocationRequiredError(Exception):
    """هذا الحقل يحتاج location_code ليُصفِّي به، ولم يُرسَل."""


@dataclass(frozen=True)
class _FieldSpec:
    types: frozenset[AccountType]
    forms: Optional[frozenset[AccountForm]]  # None = بلا قيد على form
    location_mode: str  # "param" (من الاستدعاء) · "fixed" (مُحدَّد هنا) · "none" (بلا تصفية موقع)
    fixed_location: Optional[str] = None


# النوع×الحقل → مواصفة التصفية. المفتاح الثاني هو اسم الحقل كما يرسله
# العميل (query param)، حرّ التسمية طالما موثَّق هنا وفي OperationForm.tsx.
_SPECS: dict[tuple[str, str], _FieldSpec] = {
    ("RECEIPT", "receiving"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.CASH, AccountForm.BANK, AccountForm.CORRESPONDENT}),
        location_mode="param",
    ),
    ("PAYMENT", "paying"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.CASH, AccountForm.BANK, AccountForm.CORRESPONDENT}),
        location_mode="param",
    ),
    ("EXPENSE", "paying"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.CASH, AccountForm.BANK}),
        location_mode="none",  # المصروف قد يُدفع من أي صندوق/بنك بتلك العملة بصرف النظر عن الموقع
    ),
    # EXCHANGE نطاق الخزينة (٢٠٢٦-٠٩-٢٤، طلب مالك — لا عميل، تحويل بين
    # حسابي شركة عبر مراسل طرف ثالث §١-٥): أي حساب شركة بعملة كل طرف، أي
    # موقع — حسابات العملاء (2100-*) مستبعَدة أصلاً هنا كبقية `_SPECS`
    # (نفس الاستبعاد البنيوي في `accounts_for_operation` أدناه لكل الحقول).
    # حساب عمولة الصرافة (٢٠٢٦-١٠-٠٤): حسابات الشركة بعملة العمولة المستقلة عن عملتي الصرف، أي موقع
    # (نطاق العميل يضيف حساب العميل نفسه في الواجهة عبر موقع، لا عبر هذا الملف — حسابات العملاء مستبعَدة بنيوياً هنا).
    ("EXCHANGE", "commission"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.CASH, AccountForm.BANK, AccountForm.CORRESPONDENT}),
        location_mode="none",
    ),
    ("EXCHANGE", "source"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.CASH, AccountForm.BANK, AccountForm.CORRESPONDENT}),
        location_mode="none",
    ),
    ("EXCHANGE", "destination"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.CASH, AccountForm.BANK, AccountForm.CORRESPONDENT}),
        location_mode="none",
    ),
    # CASH_TRANSFER: أربعة حقول مختلفة الدور تماماً رغم تشابه الشكل —
    # المصدر/المنفِّذ ينقلان العملة الأصلية نفسها بموقعين مختلفين،
    # التحصيل/تكلفة العمولة يخصّان عملة العمولة (قد تختلف عن المنقولة).
    #
    # ⚠ تصحيح (٢٠٢٦-٠٩-٢٢، بلاغ مالك مكرَّر): المصدر/المنفِّذ كانا يستثنيان
    # CORRESPONDENT عمداً — لكن التحقق الفعلي من القاعدة أثبت أن مكاتب
    # الشركة خارج طرابلس (تركيا وغيرها)، بل وحتى مكتب المراسل داخل طرابلس
    # نفسه (١٣١١-١٣١٣ "مكتب منصور")، **حسابات CORRESPONDENT فعلياً لا
    # CASH/BANK** — لا يوجد صندوق/بنك حرفي بمعظم المواقع أصلاً. استثناء
    # CORRESPONDENT هنا كان يمنع تنفيذ أي تحويل حقيقي بين هذه المواقع
    # بالكامل. أُضيف CORRESPONDENT الآن لنفس أسباب RECEIPT/PAYMENT أعلاه.
    ("CASH_TRANSFER", "source"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.CASH, AccountForm.BANK, AccountForm.CORRESPONDENT}),
        location_mode="param",  # موقع المصدر = from_location
    ),
    ("CASH_TRANSFER", "execution"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.CASH, AccountForm.BANK, AccountForm.CORRESPONDENT}),
        location_mode="param",  # موقع التنفيذ = to_location
    ),
    # ⚠ تصحيح ثانٍ (٢٠٢٦-٠٩-٢٣، توضيح مالك): ربط حقلي العمولة بموقع
    # الوجهة كان خطأً مفاهيمياً من الأصل — العمولة عملتها وحسابها لا علاقة
    # لهما بموقع الوجهة إطلاقاً (مثال المالك: تحويل لتركيا بعمولة **دينار
    # تُحصَّل وتُسوَّى في ليبيا**). كلا الحقلين الآن حرّا الموقع تماماً
    # (نفس نمط LOCAL_MOVE أدناه)؛ التصفية الوحيدة المتبقية عملة العمولة.
    # حقل التحصيل تحديداً له خيار ثالث لا يمرّ عبر هذا الملف إطلاقاً: رصيد
    # العميل نفسه (الافتراضي في الواجهة) — انظر `cash_transfer.py`.
    ("CASH_TRANSFER", "collection"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.CASH, AccountForm.BANK, AccountForm.CORRESPONDENT}),
        location_mode="none",
    ),
    ("CASH_TRANSFER", "cost_correspondent"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.CORRESPONDENT}),
        location_mode="none",
    ),
    ("LOCAL_MOVE", "from"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.CASH, AccountForm.BANK, AccountForm.CORRESPONDENT, AccountForm.CLEARING}),
        location_mode="none",  # نقل داخلي حرّ الموقع — القيد الوحيد هو العملة وعدم مسّ عميل
    ),
    ("LOCAL_MOVE", "to"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.CASH, AccountForm.BANK, AccountForm.CORRESPONDENT, AccountForm.CLEARING}),
        location_mode="none",
    ),
    ("SWIFT_OUT", "partner"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.CORRESPONDENT}),
        location_mode="fixed",
        fixed_location="TURKEY",  # §٤ رقم ٦: SWIFT_OUT تعريفاً "خروج دولار من تركيا" — ليس خياراً
    ),
    ("SWIFT_IN", "receiving"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.BANK}),
        location_mode="fixed",
        fixed_location="CHINA",  # بنوك الصين فقط — العملة (USD بلا سعر تحويل، أو CNY بسعر) تُحدَّد بالباراميتر
    ),
    # الإرسال الخارجي (٢٠٢٦-١٠-٠٤): حساب الشركة المُرسِل = بنك أو مراسل أو صندوق **بعملة العملية نفسها** (يوان ← حسابات اليوان فقط)،
    # أي موقع — الموقع الوحيد المهم هو موقع حساب العميل المخصوم منه، وهو حقل منفصل.
    ("REMIT_OUT", "sending"): _FieldSpec(
        types=frozenset({AccountType.ASSET}),
        forms=frozenset({AccountForm.CASH, AccountForm.BANK, AccountForm.CORRESPONDENT}),
        location_mode="none",
    ),
}


def accounts_for_operation(
    db: Session, *, operation_type: str, field: str, currency_code: str, location_code: Optional[str]
) -> list[Account]:
    key = (operation_type, field)
    if key not in _SPECS:
        raise InvalidAccountFieldError(f"لا مواصفة تصفية لـ({operation_type}, {field})")
    spec = _SPECS[key]

    effective_location_code: Optional[str]
    if spec.location_mode == "fixed":
        effective_location_code = spec.fixed_location
    elif spec.location_mode == "param":
        if not location_code:
            raise LocationRequiredError(f"الحقل ({operation_type}, {field}) يحتاج location_code")
        effective_location_code = location_code
    else:
        effective_location_code = None

    all_accounts = db.execute(select(Account).where(Account.is_active.is_(True))).scalars().all()
    parent_ids = {a.parent_id for a in all_accounts if a.parent_id is not None}
    leaves = [a for a in all_accounts if a.id not in parent_ids and a.client_id is None]

    location_id: Optional[int] = None
    if effective_location_code is not None:
        location = db.execute(select(Location).where(Location.code == effective_location_code)).scalar_one_or_none()
        location_id = location.id if location else -1  # لا موقع مطابق → لن يطابق أي حساب، قائمة فارغة صحيحة

    result = [
        a
        for a in leaves
        if a.type in spec.types
        and (spec.forms is None or a.form in spec.forms)
        and a.currency_code == currency_code
        and (location_id is None or a.location_id == location_id)
    ]
    return sorted(result, key=lambda a: a.code)
