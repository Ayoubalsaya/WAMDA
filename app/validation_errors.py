"""ترجمة أخطاء التحقق (٤٢٢) إلى العربية — معالج عام لا إصلاح حقل بعينه.

كانت FastAPI تُرجع قائمة Pydantic الخام (`[{"type":"greater_than","loc":["body",
"cost_rate"],...}]`) فيعرضها المستخدم حرفياً. الآن كل `RequestValidationError`
(جسم/استعلام/مسار/ترويسة) يصير:

    {"detail": "«سعر التكلفة»: يجب أن يكون أكبر من صفر",
     "errors": [{"loc": ["cost_rate"], "field": "cost_rate", "label": "سعر التكلفة",
                 "message": "يجب أن يكون أكبر من صفر", "type": "greater_than"}]}

`detail` نص عربي دائماً (لا JSON خام في أي مستهلك يعرضه كما هو)، و`errors` بنية
للواجهة كي تضع الرسالة تحت الحقل نفسه وتستبدل `label` بالاسم الظاهر في شاشتها.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# اسم الحقل في الطلب ← اسمه الافتراضي بالعربية (الواجهة تتجاوزه بما يظهر في شاشتها).
# `tests/test_validation_errors.py` يفرض أن كل حقل في أي مخطّط طلب موجود هنا.
FIELD_LABELS_AR: dict[str, str] = {
    "account_code": "الحساب", "acknowledged_remaining_suspense": "إقرار رصيد فروق التأسيس",
    "allow_negative": "السماح بالرصيد السالب", "amount": "المبلغ", "as_of_date": "التاريخ",
    "backdate_reason": "سبب القيد بأثر رجعي", "bank_conversion_rate": "سعر تحويل البنك",
    "body": "نص التعليق", "client_commission_amount": "عمولة العميل", "client_id": "العميل",
    "client_location_code": "موقع العميل", "client_rate": "سعر العميل", "code": "الكود",
    "collection_account_code": "حساب تحصيل العمولة", "collection_location_code": "موقع التحصيل",
    "commission_account_code": "حساب العمولة", "commission_amount": "مبلغ العمولة", "commission_currency": "عملة العمولة",
    "commission_direction": "اتجاه العمولة", "commission_location_code": "موقع حساب العمولة", "confidence": "درجة الثقة", "contact_phone": "هاتف التواصل",
    "cost_commission_amount": "تكلفة العمولة", "cost_correspondent_account_code": "حساب تكلفة العمولة (المراسل)",
    "cost_rate": "سعر التكلفة", "sending_account_code": "حساب الإرسال", "country": "الدولة", "credit_status": "حالة الائتمان", "mode": "وضع الائتمان",
    "currency_code": "العملة", "current_password": "كلمة المرور الحالية", "decimals": "عدد المنازل العشرية",
    "description": "البيان", "destination_account_code": "الحساب الوجهة", "entry_date": "تاريخ العملية",
    "entry_id": "القيد", "execution_account_code": "الحساب المنفِّذ", "expense_account_code": "بند المصروف",
    "external_ref": "المرجع الخارجي", "fee_amount": "الرسوم", "from_account_code": "من حساب",
    "from_currency": "من عملة", "from_location_code": "من موقع", "full_name": "الاسم الكامل",
    "id_number": "رقم الهوية", "initial_password": "كلمة المرور المؤقتة", "is_active": "الحالة",
    "is_debit": "الاتجاه", "limit_amount": "حد الائتمان", "lines": "بنود الكشف", "location_code": "الموقع",
    "logo_data_url": "الشعار", "matched_entry_id": "القيد المطابق", "month": "الشهر", "name_ar": "الاسم بالعربية",
    "name_en": "الاسم بالإنجليزية", "negative_margin_reason": "سبب الهامش السالب",
    "new_password": "كلمة المرور الجديدة", "note": "ملاحظة", "notes": "ملاحظات", "operation": "العملية",
    "override_reason": "سبب التجاوز", "parent_code": "الحساب الأب", "partner_account_code": "حساب الشريك",
    "partner_id": "الشريك", "password": "كلمة المرور", "paying_account_code": "الحساب المصروف منه",
    "payment_method": "طريقة الدفع", "period_from": "من تاريخ", "period_to": "إلى تاريخ", "phone": "الهاتف",
    "reason": "السبب", "receiving_account_code": "الحساب المستقبِل", "return_fee_amount": "رسوم الإرجاع",
    "role": "الدور",
    "sort_order": "ترتيب العرض", "source_account_code": "الحساب المصدر", "source_note": "ملاحظة المصدر",
    "source_type": "مصدر الرصيد", "step1": "الخطوة ١", "step2": "الخطوة ٢", "swift_movement_id": "حركة السويفت",
    "symbol": "الرمز", "to_account_code": "إلى حساب", "to_currency": "إلى عملة", "to_location_code": "إلى موقع",
    "token": "رمز الدعوة", "total_amount": "المبلغ", "totp_code": "رمز المصادقة", "backup_code": "الرمز الاحتياطي",
    "totp_secret_setup": "سرّ المصادقة", "username": "اسم المستخدم", "value_date": "التاريخ", "year": "السنة",
    # معاملات الاستعلام/المسار/الترويسة
    "q": "نص البحث", "date": "التاريخ", "date_from": "من تاريخ", "date_to": "إلى تاريخ", "from": "من تاريخ",
    "to": "إلى تاريخ", "limit": "الحد الأقصى للنتائج", "offset": "بداية النتائج", "size": "الحجم",
    "currency": "العملة", "location": "الموقع", "min_amount": "الحد الأدنى للمبلغ", "entry_no": "رقم القيد",
    "chain_ref": "مرجع السلسلة", "operation_type": "نوع العملية", "field": "الحقل", "action": "الإجراء",
    "actor_type": "نوع المنفِّذ", "entity": "الكيان", "granularity": "التجميع", "include_reversed": "إظهار الملغاة",
    "lot_id": "الدفعة", "line_id": "البند", "statement_id": "الكشف", "user_id": "المستخدم", "report_key": "التقرير",
    "Idempotency-Key": "مفتاح عدم التكرار", "idempotency-key": "مفتاح عدم التكرار",
}

_GENERIC_FIELD = "قيمة الطلب"
_PREFIX_ROOTS = {"body", "query", "path", "header", "cookie"}
_ARABIC = re.compile(r"[؀-ۿ]")


def _number(v: Any) -> str:
    return "صفر" if str(v) in ("0", "0.0") else str(v)


def _message(err: dict[str, Any]) -> str:
    kind = err.get("type", "")
    ctx = err.get("ctx") or {}
    if kind == "missing":
        return "هذا الحقل مطلوب"
    if kind == "greater_than":
        return f"يجب أن يكون أكبر من {_number(ctx.get('gt'))}"
    if kind == "greater_than_equal":
        return "يجب ألا يكون سالباً" if str(ctx.get("ge")) in ("0", "0.0") else f"يجب ألا يقل عن {ctx.get('ge')}"
    if kind == "less_than":
        return f"يجب أن يكون أقل من {_number(ctx.get('lt'))}"
    if kind == "less_than_equal":
        return f"يجب ألا يزيد عن {_number(ctx.get('le'))}"
    if kind in ("decimal_parsing", "decimal_type", "float_parsing", "float_type", "finite_number"):
        return "يجب أن يكون رقماً صحيحاً (مثل 9.05)"
    if kind in ("decimal_max_places",):
        return f"عدد المنازل العشرية أكبر من المسموح ({ctx.get('decimal_places')})"
    if kind in ("decimal_max_digits", "decimal_whole_digits"):
        return "الرقم أكبر من المسموح"
    if kind in ("int_parsing", "int_type", "int_from_float", "int_parsing_size"):
        return "يجب أن يكون عدداً صحيحاً"
    if kind == "string_type":
        return "يجب أن يكون نصاً"
    if kind == "string_too_short":
        return "هذا الحقل مطلوب" if ctx.get("min_length") == 1 else f"قصير جداً (الحد الأدنى {ctx.get('min_length')} أحرف)"
    if kind == "string_too_long":
        return f"طويل جداً (الحد الأقصى {ctx.get('max_length')} حرفاً)"
    if kind == "string_pattern_mismatch":
        return "الصيغة غير صحيحة"
    if kind in ("bool_parsing", "bool_type"):
        return "قيمة غير صالحة (نعم/لا)"
    if kind.startswith(("date", "datetime", "time")):
        return "تاريخ غير صالح (الصيغة: السنة-الشهر-اليوم)"
    if kind in ("enum", "literal_error"):
        return "قيمة غير مسموحة"
    if kind == "too_short":
        return "يجب إدخال بند واحد على الأقل"
    if kind == "too_long":
        return "عدد البنود أكبر من المسموح"
    if kind == "extra_forbidden":
        return "حقل غير معروف"
    if kind == "json_invalid":
        return "الطلب ليس بصيغة صحيحة"
    if kind in ("model_attributes_type", "model_type", "dict_type", "list_type"):
        return "صيغة الطلب غير صحيحة"
    if kind == "value_error":
        text = re.sub(r"^Value error,\s*", "", str(err.get("msg", "")))
        return text if _ARABIC.search(text) else "قيمة غير صالحة"
    return "قيمة غير صالحة"


def translate_validation_errors(raw_errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for err in raw_errors:
        loc = list(err.get("loc", ()))
        if loc and isinstance(loc[0], str) and loc[0] in _PREFIX_ROOTS:
            loc = loc[1:]  # الجذر فقط (body/query/…) — حقل اسمه "body" داخل الجسم يبقى
        field = next((p for p in reversed(loc) if isinstance(p, str)), None)
        label = FIELD_LABELS_AR.get(field, _GENERIC_FIELD) if field else None
        if err.get("type") == "extra_forbidden" and field and field not in FIELD_LABELS_AR:
            label = field  # حقل مجهول: يُسمّى كما وصل كي يعرف المرسِل أيّ حقل رُفض
        out.append({"loc": loc, "field": field, "label": label, "message": _message(err), "type": err.get("type", "")})
    return out


def detail_text(errors: list[dict[str, Any]]) -> str:
    parts = [f"«{e['label']}»: {e['message']}" if e["label"] else e["message"] for e in errors]
    return "؛ ".join(dict.fromkeys(parts)) or "بيانات الطلب غير صالحة"


async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = translate_validation_errors(list(exc.errors()))
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder({"detail": detail_text(errors), "errors": errors}),
    )
