"""لا JSON خام ولا إنجليزية Pydantic تصل المستخدم أبداً، وأخطاء التحقق بالعربية تحت
الحقول بأسمائها الظاهرة (٢٠٢٦-١٠-٠٢، ملاحظة مالك):
`[{"type":"greater_than","loc":["body","cost_rate"],...}]` ظهرت حرفياً في الشاشة.

متصفح حقيقي على النسخة المبنية + خادم مؤقت (انظر `ui_support.py`):
  · ٤٢٢ **حقيقي** من الخادم لكل تبويب في دفتر اليومية ← رسالة عربية تحت الحقل نفسه؛
  · قائمة Pydantic خام مُحقَنة (مصدر غير مترجَم) ← رسالة عربية عامة، لا JSON؛
  · انقطاع الشبكة ورد HTML غير JSON ← رسالتان عربيتان، لا «Failed to fetch» ولا «Unexpected token».
في كل حالة يُفحَص **نص الصفحة كاملاً** بحثاً عن أي أثر خام.
"""

from __future__ import annotations

import re

import pytest

from tests.ui_support import (  # noqa: F401  (الـfixtures تُلتقَط بالاسم)
    NEEDS_CLIENT, _composer, _open_tab, _select_client, journal_page, live_server, qa_identity,
)

ARABIC = re.compile(r"[\u0600-\u06FF]")
RAW = re.compile(
    r'"type"|"loc"|"ctx"|"msg"|\[\{|\{"|Input should|Field required|greater_than|value_error|decimal_parsing|'
    r"Failed to fetch|NetworkError|Unexpected token|SyntaxError|DecimalError|<html|undefined|\[object"
)

SCENARIOS = [
    ("RECEIPT", None), ("PAYMENT", None), ("EXCHANGE", "CLIENT"), ("EXCHANGE", "TREASURY"),
    ("CASH_TRANSFER", None), ("REMIT_OUT", None), ("EXPENSE", None), ("SWIFT_OUT", None), ("SWIFT_IN", None),
    ("LOCAL_MOVE", None), ("OPENING", None), ("ADJUSTMENT", None),
]


def _page_text(pg) -> str:
    return pg.locator("body").inner_text()


def _assert_no_raw(pg, where: str):
    text = _page_text(pg)
    found = RAW.search(text)
    assert not found, f"{where}: أثر خام «{found.group(0)}» ظاهر في الصفحة"


def _prepare(pg, op: str, scope: str | None):
    pg.mode = "real"
    _open_tab(pg, op)
    if op in NEEDS_CLIENT:
        _select_client(pg)
    if scope == "TREASURY":
        _composer(pg).locator("button").filter(has_text="خزينة").first.click()
        pg.wait_for_timeout(300)


@pytest.mark.parametrize("op,scope", SCENARIOS, ids=[f"{o}-{s}" if s else o for o, s in SCENARIOS])
def test_real_server_422_is_arabic_under_the_field(journal_page, op, scope):
    """نموذج فارغ يُرسَل للخادم الحقيقي ← ٤٢٢ حقيقي ← رسالة عربية باسم الحقل تحته."""
    pg = journal_page
    _prepare(pg, op, scope)
    n = len(pg.sent)
    with pg.expect_response(lambda r: r.request.method == "POST" and "/operations/" in r.url) as info:
        _composer(pg).get_by_role("button", name="حفظ وترحيل", exact=True).click()
    resp = info.value
    assert resp.status == 422, f"{op}: توقّعنا ٤٢٢ حقيقياً، جاء {resp.status}: {resp.text()[:200]}"
    assert len(pg.sent) == n + 1
    body = resp.json()
    assert isinstance(body["detail"], str) and ARABIC.search(body["detail"]), body
    pg.wait_for_timeout(400)

    errors = _composer(pg).locator("[data-field-error]")
    assert errors.count() >= 1, f"{op}: لا رسالة خطأ ظاهرة"
    for i in range(errors.count()):
        assert ARABIC.search(errors.nth(i).inner_text()), errors.nth(i).inner_text()
        assert "«" in errors.nth(i).inner_text(), "الرسالة لا تسمّي الحقل"
    # المبلغ (أو ما يقابله) ظاهر تحت الحقل نفسه: العنصر داخل .field
    placed_in_field = _composer(pg).locator(".field [data-field-error]").count()
    assert placed_in_field >= 1, f"{op}: لا رسالة وُضعت تحت حقل"
    _assert_no_raw(pg, op)


def test_original_report_cost_rate_zero_under_the_cost_field(journal_page):
    pg = journal_page
    pg.mode = "real"
    _open_tab(pg, "EXCHANGE")
    _select_client(pg)
    comp = _composer(pg)
    inputs = comp.locator('.composer-panel input[inputmode="decimal"]')  # المبلغ، سعر العميل، سعر التكلفة
    for i, v in enumerate(["100", "9.80", "0"]):
        inputs.nth(i).fill("")
        inputs.nth(i).press_sequentially(v, delay=20)
    with pg.expect_response(lambda r: r.request.method == "POST" and "/operations/exchange" in r.url) as info:
        comp.get_by_role("button", name="حفظ وترحيل", exact=True).click()
    assert info.value.status == 422
    pg.wait_for_timeout(400)
    cost_field = comp.locator(".field", has=pg.locator("label.field-label", has_text="سعر التكلفة")).first
    assert cost_field.locator("[data-field-error]").inner_text() == "«سعر التكلفة»: يجب أن يكون أكبر من صفر"
    _assert_no_raw(pg, "cost_rate=0")


def test_raw_pydantic_shape_never_reaches_the_screen(journal_page):
    """حتى لو جاء الردّ بالشكل الخام القديم من أي مصدر، تُعرض رسالة عربية عامة."""
    pg = journal_page
    pg.mode = "raw422"
    _open_tab(pg, "EXPENSE")
    _composer(pg).get_by_role("button", name="حفظ وترحيل", exact=True).click()
    pg.wait_for_timeout(500)
    assert "بيانات غير صالحة" in _page_text(pg)
    _assert_no_raw(pg, "raw422")


def test_network_failure_message_is_arabic(journal_page):
    pg = journal_page
    pg.mode = "abort"
    _open_tab(pg, "EXPENSE")
    _composer(pg).get_by_role("button", name="حفظ وترحيل", exact=True).click()
    pg.wait_for_timeout(500)
    assert "تعذّر الاتصال بالخادم" in _page_text(pg)
    _assert_no_raw(pg, "abort")


def test_non_json_server_reply_message_is_arabic(journal_page):
    pg = journal_page
    pg.mode = "html502"
    _open_tab(pg, "EXPENSE")
    _composer(pg).get_by_role("button", name="حفظ وترحيل", exact=True).click()
    pg.wait_for_timeout(500)
    assert "تعذّر تنفيذ الطلب (خطأ 502)" in _page_text(pg)
    _assert_no_raw(pg, "html502")


def test_raw_shape_on_other_screens_create_client_modal(journal_page):
    """خارج دفتر اليومية أيضاً: نافذة «عميل جديد» ← ٤٢٢ خام مُحقَن ← لا JSON."""
    pg = journal_page
    pg.mode = "stub"

    def raw(route):
        if route.request.method == "POST":
            route.fulfill(status=422, content_type="application/json", body=(
                '{"detail":[{"type":"missing","loc":["body","name_ar"],"msg":"Field required","input":{}}]}'))
        else:
            route.continue_()

    pg.route("**/clients", raw)
    try:
        pg.click("button[title^='العملاء']")
        pg.wait_for_selector(".clients-screen")
        pg.get_by_role("button", name=re.compile("عميل جديد")).first.click()
        pg.fill("#new-client-code", "QA-RAW-1")
        pg.fill("#new-client-name", "اختبار")
        pg.get_by_role("button", name="حفظ", exact=True).click()
        pg.wait_for_timeout(500)
        assert "بيانات غير صالحة" in _page_text(pg)
        _assert_no_raw(pg, "create-client")
    finally:
        pg.unroute("**/clients", raw)
        pg.get_by_role("button", name="إلغاء", exact=True).click()
        pg.click("button[title^='دفتر اليومية']")
        pg.wait_for_selector(".journal-col-center")
