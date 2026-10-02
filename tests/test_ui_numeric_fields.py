"""اختبار انحدار بمتصفح حقيقي: **القيمة المرسلة = القيمة المعروضة** في كل حقول
المبالغ والأسعار بكل تبويبات دفتر اليومية (٢٠٢٦-١٠-٠٢، ملاحظة مالك: الحقل كان
يعرض ٩٫٠٥ لكن الخطأ المعروض يقول إن الخادم استلم `cost_rate="0"`).

السبب الجذري المُثبَت: ردّ ٤٢٢ لمحاولة سابقة (cost_rate=0) كان يبقى ظاهراً بجوار
حقل صُحِّح إلى ٩٫٠٥ (الحالة والإرسال سليمان). وصنف قريب منه: إدخال أرقام عربية
أو نص غير رقمي يرمي `DecimalError` داخل معاينة الصرافة فتسقط الواجهة كلها.

الاختبار يعمل على النسخة المبنية (`npm run build` → app/static/app) من خادم uvicorn
مؤقت على منفذ حر؛ طلبات الكتابة `/operations/*` تُعترَض وتُرَدّ بـ٤٢٢ مُصطنَع فلا
يُرحَّل أي قيد — فقط يُنشأ مستخدم وعميل QA مؤقتان يُنظَّفان بعده. يُتخطّى إن غابت
Playwright أو المتصفح أو النسخة المبنية.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.ui_support import (  # noqa: F401  (الـfixtures تُلتقَط بالاسم)
    DISTINCT_VALUES, NEEDS_CLIENT, _composer, _decimal_inputs, _numeric_values, _open_tab, _save, _select_client,
    journal_page, live_server, qa_identity,
)

pytestmark = pytest.mark.skipif(not (Path(__file__).resolve().parent.parent / "app" / "static" / "app" / "index.html").exists(),
                                reason="النسخة المبنية للواجهة غير موجودة (npm run build)")

SCENARIOS = [
    ("RECEIPT", None), ("PAYMENT", None), ("EXCHANGE", "CLIENT"), ("EXCHANGE", "TREASURY"),
    ("CASH_TRANSFER", None), ("REMIT_OUT", None), ("EXPENSE", None), ("SWIFT_OUT", None), ("SWIFT_IN", None),
    ("LOCAL_MOVE", None), ("OPENING", None), ("ADJUSTMENT", None),
]


@pytest.mark.parametrize("op,scope", SCENARIOS, ids=[f"{o}-{s}" if s else o for o, s in SCENARIOS])
def test_every_numeric_field_sent_equals_displayed(journal_page, op, scope):
    """كل قيمة رقمية معروضة في أي حقل مبلغ/سعر تظهر حرفياً في الطلب، ولا قيمة
    رقمية تُرسَل لم تكن معروضة (لا `0` ولا تحويل صامت)."""
    pg = journal_page
    _open_tab(pg, op)
    if op in NEEDS_CLIENT:
        _select_client(pg)
    if scope == "TREASURY":
        _composer(pg).locator("button").filter(has_text="خزينة").first.click()
        pg.wait_for_timeout(300)

    inputs = _decimal_inputs(pg)
    count = inputs.count()
    assert count >= 1, f"لا حقول رقمية في {op}"
    displayed = []
    for i in range(count):
        el = inputs.nth(i)
        value = DISTINCT_VALUES[i]
        el.fill("")
        el.press_sequentially(value, delay=20)  # ضغطات حقيقية لا تعيين مباشر
        displayed.append(el.input_value())
    assert displayed == DISTINCT_VALUES[:count], "الحقل لا يعرض ما كُتب"

    requests = _save(pg)
    assert len(requests) == 1, f"{op}: لم يُرسَل طلب واحد ({len(requests)})"
    sent_values = _numeric_values(requests[0]["body"])
    assert sent_values == sorted(displayed), f"{op}: المعروض {sorted(displayed)} ≠ المُرسَل {sent_values}"


def test_arabic_digits_are_normalised_not_a_crash(journal_page):
    """أرقام عربية-هندية وفاصلة «٫»: تُحوَّل في الحقل نفسه إلى ٩٫٠٥ لاتينية، فالمعروض
    = المُرسَل، والواجهة لا تسقط (كان DecimalError يُفرغ الصفحة)."""
    pg = journal_page
    _open_tab(pg, "EXCHANGE")
    _select_client(pg)
    comp = _composer(pg)
    inputs = _decimal_inputs(pg)
    inputs.nth(0).fill("")
    inputs.nth(0).press_sequentially("٩٫٠٥", delay=20)
    assert inputs.nth(0).input_value() == "9.05"
    assert pg.evaluate("document.getElementById('root').children.length") > 0
    assert comp.is_visible()
    requests = _save(pg)
    assert requests and requests[0]["body"]["amount"] == "9.05"


@pytest.mark.parametrize("raw", ["1,000", "9,05", "abc", "9.05.1"])
def test_invalid_number_is_flagged_not_sent_and_does_not_crash(journal_page, raw):
    pg = journal_page
    _open_tab(pg, "EXPENSE")
    inputs = _decimal_inputs(pg)
    inputs.nth(0).fill("")
    inputs.nth(0).press_sequentially(raw, delay=20)
    assert pg.evaluate("document.getElementById('root').children.length") > 0, "سقطت الواجهة"
    assert _composer(pg).locator("[role=alert].field-error").count() == 1  # رسالة عربية تحت الحقل
    assert _save(pg) == []  # لا طلب بقيمة غير صالحة
    assert "المبلغ" in _composer(pg).locator(".form-guide[role=alert]").first.inner_text()  # رسالة عربية باسم الحقل


def test_stale_server_error_disappears_when_the_field_is_corrected(journal_page):
    """السيناريو الأصلي: محاولة أولى بسعر تكلفة ٠ ← رفض ← تصحيح الحقل إلى ٩٫٠٥ ←
    الخطأ القديم يجب ألا يبقى ظاهراً بجوار الحقل المُصحَّح."""
    pg = journal_page
    _open_tab(pg, "EXCHANGE")
    _select_client(pg)
    comp = _composer(pg)
    inputs = _decimal_inputs(pg)  # المبلغ، سعر العميل، سعر التكلفة
    for i, v in enumerate(["100", "9.80", "0"]):
        inputs.nth(i).fill("")
        inputs.nth(i).press_sequentially(v, delay=20)
    first = _save(pg)
    assert first and first[0]["body"]["cost_rate"] == "0"
    assert comp.locator("[role=alert]").count() == 1, "الخطأ يجب أن يظهر بعد الرفض"

    inputs.nth(2).fill("")
    inputs.nth(2).press_sequentially("9.05", delay=20)
    assert inputs.nth(2).input_value() == "9.05"
    assert comp.locator("[role=alert]").count() == 0, "بقي خطأ المحاولة السابقة بجوار الحقل المُصحَّح"
    second = _save(pg)
    assert second and second[0]["body"]["cost_rate"] == "9.05"
