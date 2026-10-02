"""الإضافة السريعة لعميل من دفتر اليومية (٢٠٢٦-١٠-٠٢) — متصفح حقيقي على النسخة المبنية + خادم مؤقت.

· اسم غير موجود ← زر «+ إضافة "الاسم" كعميل جديد» ← نافذة بالاسم معبّأً ← إنشاء بزر صريح فقط ← العميل مختار ←
  نموذج العملية محتفظ بقيمه ← الترحيل ينجح (على الخادم الحقيقي: قيد فعلي على قاعدة الاختبار، يُنظَّف في النهاية)؛
· «احمد» تجد «أحمد» (بحث مُطبَّع)؛
· اسم مشابه لموجود ← تنبيه «هل تقصد أحد هؤلاء؟» ← اختيار الموجود لا ينشئ جديداً ← «لا، أنشئ» ينشئ؛
· مستخدم بلا صلاحية CREATE_CLIENT لا يرى الزر؛
· الإنتر داخل النافذة لا ينشئ عميلاً."""

from __future__ import annotations

import json
import re

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Client
from tests import factories as f
from tests.ui_support import _composer, _open_tab, journal_page, live_server, qa_identity  # noqa: F401


def _count_clients(name_like: str) -> int:
    db = SessionLocal()
    try:
        return db.execute(select(func.count()).select_from(Client).where(Client.name_ar.like(f"%{name_like}%"))).scalar_one()
    finally:
        db.close()


def _make_client(name: str) -> None:
    db = SessionLocal()
    try:
        db.add(Client(code=f"QA-QC-{f.uid()[:6].upper()}", name_ar=name, search_name=name))
        db.commit()
    finally:
        db.close()


def _search(pg, text: str):
    box = pg.locator("#client-search")
    box.fill("")
    box.fill(text)
    pg.wait_for_timeout(700)  # debounce ٢٠٠ms + الرد


def _reset_to_journal(pg):
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")


def _currency_select(pg, comp):
    return comp.locator(".field", has=pg.locator("label.field-label", has_text="العملة")).locator("select").first


def test_unknown_name_quick_create_keeps_the_operation_form_and_posts(journal_page):
    pg = journal_page
    pg.mode = "real"
    _reset_to_journal(pg)
    _open_tab(pg, "RECEIPT")
    comp = _composer(pg)
    # قيم يملؤها المستخدم قبل أن يكتشف أن العميل غير موجود
    comp.locator("#op-amount").fill("123.45")
    comp.locator("#op-note").fill("ملاحظة قبل إضافة العميل")
    _currency_select(pg, comp).select_option("LYD")

    name = f"عميل سريع جديد {f.uid()[:6]}"
    _search(pg, name)
    btn = pg.locator("button.client-quick-create")
    assert btn.count() == 1 and f'إضافة "{name}" كعميل جديد' in btn.inner_text()

    posted = []
    pg.on("request", lambda r: posted.append(r.url) if r.method == "POST" and r.url.endswith("/clients") else None)
    btn.click()
    modal = pg.locator(".modal-veil")
    assert modal.locator("#new-client-name").input_value() == name  # الاسم من نص البحث
    code = f"QA-QC-{f.uid()[:6].upper()}"
    modal.locator("#new-client-code").fill(code)
    modal.locator("#new-client-code").press("Enter")  # لا اختصار لوحة مفاتيح ينشئ عميلاً
    pg.wait_for_timeout(500)
    assert modal.is_visible() and not posted, "الإنتر أنشأ عميلاً!"
    modal.get_by_role("button", name="حفظ", exact=True).click()
    pg.wait_for_selector(".client-profile", timeout=10000)
    assert len(posted) == 1
    assert name in pg.locator(".client-profile").inner_text()  # اختير تلقائياً في العدسة
    assert not modal.is_visible()
    # لم يضِع شيء من نموذج العملية
    assert comp.locator("#op-amount").input_value() == "123.45"
    assert comp.locator("#op-note").input_value() == "ملاحظة قبل إضافة العميل"
    assert _currency_select(pg, comp).input_value() == "LYD"

    # أكمل العملية وارحّلها فعلاً
    comp.locator(".field", has=pg.locator("label.field-label", has_text=re.compile(r"^\s*الموقع\s*$"))).locator("select").select_option("TRIPOLI")
    acct = comp.locator(".acct-picker")
    acct.locator("button.acct-picker-trigger").click()
    acct.locator(".acct-picker-row").filter(has_text="1101").first.click()
    with pg.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/operations/receipt")) as info:
        comp.get_by_role("button", name="حفظ وترحيل", exact=True).click()
    assert info.value.status == 201, info.value.text()
    assert _count_clients(name) == 1


def test_search_finds_hamza_variants(journal_page):
    pg = journal_page
    pg.mode = "stub"
    _reset_to_journal(pg)
    tail = f.uid()[:6]
    _make_client(f"أحمد الورفلي {tail}")
    _search(pg, f"احمد الورفلي {tail}")  # بلا همزة
    assert pg.locator(".client-result").filter(has_text=f"أحمد الورفلي {tail}").count() == 1
    assert pg.locator("button.client-quick-create").count() == 0  # وُجد فلا زر إضافة


def test_similar_name_warns_and_choosing_existing_creates_nothing(journal_page):
    pg = journal_page
    pg.mode = "stub"
    _reset_to_journal(pg)
    tail = f.uid()[:6]
    existing = f"محمد المنصوري {tail}"
    _make_client(existing)
    typed = f"محمد المنصوريه {tail}"  # حرف زائد: البحث لا يجده لكنه مشابه جداً
    _search(pg, typed)
    assert pg.locator("button.client-quick-create").count() == 1
    before = _count_clients(tail)
    pg.locator("button.client-quick-create").click()
    modal = pg.locator(".modal-veil")
    modal.locator("#new-client-code").fill(f"QA-QC-{f.uid()[:6].upper()}")
    modal.get_by_role("button", name="حفظ", exact=True).click()
    warn = modal.locator("[data-testid=similar-clients]")
    warn.wait_for(timeout=10000)
    assert "هل تقصد أحد هؤلاء؟" in warn.inner_text() and existing in warn.inner_text()
    warn.get_by_role("button", name="اختيار").first.click()
    pg.wait_for_selector(".client-profile")
    assert existing in pg.locator(".client-profile").inner_text()
    assert not modal.is_visible()
    assert _count_clients(tail) == before, "اختيار الموجود أنشأ عميلاً جديداً"

    # «لا، أنشئ عميلاً جديداً» ينشئ فعلاً
    pg.locator("button.mini-icon").click()  # مسح العميل
    _search(pg, typed)
    pg.locator("button.client-quick-create").click()
    modal.locator("#new-client-code").fill(f"QA-QC-{f.uid()[:6].upper()}")
    modal.get_by_role("button", name="حفظ", exact=True).click()
    modal.locator("[data-testid=similar-clients]").wait_for()
    modal.get_by_role("button", name="لا، أنشئ عميلاً جديداً").click()
    pg.wait_for_selector(".client-profile")
    assert _count_clients(tail) == before + 1


def test_user_without_create_client_permission_does_not_see_the_button(journal_page):
    pg = journal_page
    pg.mode = "stub"

    def no_permission(route):
        resp = route.fetch()
        body = resp.json()
        body["permissions"] = [p for p in body["permissions"] if p != "CREATE_CLIENT"]
        route.fulfill(response=resp, body=json.dumps(body))

    pg.route("**/auth/me", no_permission)
    try:
        _reset_to_journal(pg)
        _search(pg, f"اسم غير موجود إطلاقاً {f.uid()[:6]}")
        assert pg.locator(".client-result").count() == 0
        assert pg.locator("button.client-quick-create").count() == 0
    finally:
        pg.unroute("**/auth/me", no_permission)
        _reset_to_journal(pg)
