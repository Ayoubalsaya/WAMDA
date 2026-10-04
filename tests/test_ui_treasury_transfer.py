"""«تحويل بعمولة» بنطاقين «عميل / خزينة» واجهةً فقط (٢٠٢٦-١٠-٠٥): نطاق الخزينة يرسل إلى مسار LOCAL_MOVE نفسه — بلا عميل،
بحقول النقل الداخلي، وعمولة اختيارية بالمكوّن المشترك — ونطاق العميل لا يتغيّر. وسبب تعطيل زر الترحيل ظاهر بجانبه دائماً.

(الطلب يُلتقط بوضع `stub` كي لا تتلوّث قاعدة الاختبار بقيد خزينة دائم لا يمسحه تنظيف QA؛ القيد الفعلي والإلغاء والتعديل
على الخادم في `test_local_move_commission.py`، وفتح التعديل مملوءاً في `test_ui_edit_prefill.py`.)"""

from __future__ import annotations

import re

from tests.ui_support import NEEDS_CLIENT, TAB_LABEL, _composer, _open_tab, journal_page, live_server, qa_identity  # noqa: F401

REASON = "[data-testid=submit-disabled-reason]"


def _fresh(pg):
    pg.mode = "stub"
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    pg.wait_for_timeout(500)


def _post_button(comp):
    return comp.get_by_role("button", name="حفظ وترحيل", exact=True)


def _scope(comp, label):
    comp.locator("button", has_text=re.compile(rf"^\s*{label}\s*$")).first.click()


def _sel(pg, comp, label_rx):
    return comp.locator(".field", has=pg.locator("label.field-label", has_text=re.compile(label_rx))).locator("select").first


def _pick(comp, index, nth_row):
    picker = comp.locator(".acct-picker").nth(index)
    picker.locator("button.acct-picker-trigger").click()
    rows = picker.locator(".acct-picker-row")
    rows.first.wait_for(timeout=5000)
    rows.nth(nth_row).click()


def test_client_scope_unchanged_and_disabled_button_says_why(journal_page):
    pg = journal_page
    _fresh(pg)
    _open_tab(pg, "CASH_TRANSFER")
    comp = _composer(pg)
    # نطاق العميل كما كان: عمولة العميل (تحصيل) ومن رصيد العميل وموقعا من/إلى
    text = comp.inner_text()
    for needle in ("عمولة العميل (تحصيل)", "من رصيد العميل", "من موقع", "تكلفة العمولة", "حساب المصدر (الشركة)"):
        assert needle in text, needle
    assert _post_button(comp).is_disabled()
    reason = comp.locator(REASON)
    assert reason.count() == 1 and "اختر عميلاً" in reason.inner_text() and "خزينة" in reason.inner_text(), reason.all_inner_texts()
    # الاختيار الفعلي لعميل يرفع التعطيل ويُخفي السبب
    pg.fill("#client-search", pg.client_code)
    pg.locator(".client-result", has_text=pg.client_code).first.click()
    pg.wait_for_selector(".client-profile")
    assert _post_button(comp).is_enabled() and comp.locator(REASON).count() == 0


def test_treasury_scope_needs_no_client_and_posts_to_the_local_move_path(journal_page):
    pg = journal_page
    _fresh(pg)
    _open_tab(pg, "CASH_TRANSFER")
    comp = _composer(pg)
    assert _post_button(comp).is_disabled()  # بلا عميل في نطاق العميل
    _scope(comp, "خزينة")
    pg.wait_for_timeout(300)

    # لا عميل مطلوب: الزر فعّال ولا سبب ولا شريط «اختر عميلاً»، وحقول النقل الداخلي وحدها
    assert _post_button(comp).is_enabled() and comp.locator(REASON).count() == 0
    text = comp.inner_text()
    assert "اختر عميلاً" not in text
    for gone in ("من رصيد العميل", "عمولة العميل (تحصيل)", "من موقع", "تكلفة العمولة", "حساب تحصيل العمولة"):
        assert gone not in text, gone
    for kept in ("الحساب المصدر", "الحساب المنفِّذ", "ملاحظة"):
        assert kept in text, kept
    assert comp.locator("#localmove-amount").count() == 1
    assert _sel(pg, comp, r"^\s*العملة\s*$").count() == 1

    _sel(pg, comp, r"^\s*العملة\s*$").select_option("USD")
    _pick(comp, 0, 0)
    _pick(comp, 1, 1)
    comp.locator("#localmove-amount").fill("500")
    comp.locator("#op-note").fill("تحويل من مكتب منصور إلى الواثقون")

    # العمولة مطويّة افتراضياً، والاتجاه الافتراضي «ندفعها» (الحالة الغالبة)، بلا خيار «حساب العميل»
    section = comp.locator("[data-testid=localmove-commission-section]")
    toggle = section.locator(".commission-toggle")
    assert toggle.get_attribute("aria-expanded") == "false"
    toggle.click()
    paid = section.locator(".commission-body [role=tab]", has_text="ندفعها")
    assert paid.get_attribute("aria-selected") == "true"
    assert section.locator(".commission-body [role=tab]", has_text="حساب العميل").count() == 0
    _sel(pg, section, r"^\s*عملة العمولة\s*$").select_option("USD")
    section.locator("#localmove-commission-amount").fill("5")
    comm_picker = section.locator(".acct-picker")
    comm_picker.locator("button.acct-picker-trigger").click()
    rows = comm_picker.locator(".acct-picker-row")
    rows.first.wait_for(timeout=5000)
    assert all("دولار" in t for t in rows.all_inner_texts()), rows.all_inner_texts()  # مفلتر بعملة العمولة
    rows.first.click()

    n = len(pg.sent)
    _post_button(comp).click()
    pg.wait_for_timeout(600)
    sent = pg.sent[n:]
    assert len(sent) == 1, sent
    assert sent[0]["url"].endswith("/operations/local-move"), sent[0]["url"]  # المسار نفسه — لا cash-transfer
    body = sent[0]["body"]
    assert "client_id" not in body and "fee_amount" not in body and "collection_account_code" not in body
    assert body["currency_code"] == "USD" and body["amount"] == "500" and body["note"] == "تحويل من مكتب منصور إلى الواثقون"
    assert body["from_account_code"] and body["to_account_code"] and body["from_account_code"] != body["to_account_code"]
    assert body["commission_direction"] == "OUT" and body["commission_currency"] == "USD" and body["commission_amount"] == "5"
    assert body["commission_account_code"] and body.get("commission_location_code") is None


def test_treasury_scope_without_commission_sends_no_commission_fields(journal_page):
    pg = journal_page
    _fresh(pg)
    _open_tab(pg, "CASH_TRANSFER")
    comp = _composer(pg)
    _scope(comp, "خزينة")
    pg.wait_for_timeout(300)
    _sel(pg, comp, r"^\s*العملة\s*$").select_option("USD")
    _pick(comp, 0, 0)
    _pick(comp, 1, 1)
    comp.locator("#localmove-amount").fill("120")
    n = len(pg.sent)
    _post_button(comp).click()
    pg.wait_for_timeout(600)
    body = pg.sent[n:][0]["body"]
    assert not any(k.startswith("commission_") and v is not None for k, v in body.items()), body


def test_switching_scope_back_restores_the_client_form_and_requirement(journal_page):
    pg = journal_page
    _fresh(pg)
    _open_tab(pg, "CASH_TRANSFER")
    comp = _composer(pg)
    _scope(comp, "خزينة")
    pg.wait_for_timeout(200)
    assert _post_button(comp).is_enabled()
    _scope(comp, "عميل")
    pg.wait_for_timeout(200)
    assert _post_button(comp).is_disabled() and "اختر عميلاً" in comp.locator(REASON).inner_text()
    assert "عمولة العميل (تحصيل)" in comp.inner_text()


def test_local_move_tab_keeps_its_own_form_without_the_old_fee_field(journal_page):
    pg = journal_page
    _fresh(pg)
    _open_tab(pg, "LOCAL_MOVE")
    comp = _composer(pg)
    text = comp.inner_text()
    assert "رسوم (اختياري" not in text and "5200" not in text
    assert "من حساب" in text and "إلى حساب" in text and "عمولة (اختياري)" in text
    assert _post_button(comp).is_enabled() and comp.locator(REASON).count() == 0


def test_every_client_tab_explains_a_disabled_button(journal_page):
    """أي تبويب يشترط عميلاً: الزر معطَّل وسببه ظاهر بجانبه (لا زر معطَّل بلا تفسير)."""
    pg = journal_page
    _fresh(pg)
    for op in sorted(NEEDS_CLIENT):
        _open_tab(pg, op)
        comp = _composer(pg)
        button = _post_button(comp)
        assert button.is_disabled(), op
        reason = comp.locator(REASON)
        assert reason.count() == 1 and reason.inner_text().strip(), (op, TAB_LABEL[op])
        assert "عميل" in reason.inner_text(), (op, reason.inner_text())


def test_wizard_buttons_explain_why_they_are_disabled(journal_page):
    pg = journal_page
    _fresh(pg)
    pg.get_by_role("button", name=re.compile("معالج الخطوتين")).first.click()
    wiz = pg.locator(".jr-modal")
    wiz.wait_for()
    next_btn = wiz.get_by_role("button", name="التالي", exact=True)
    assert next_btn.is_disabled()
    reason = wiz.locator(REASON)
    assert reason.count() == 1 and reason.inner_text().strip()
