"""حجم الأيقونات **المعروض فعلاً** (٢٠٢٦-١٠-٠٣): نقيس `getBoundingClientRect()` لعناصر `svg` في متصفح حقيقي على النسخة المبنية،
لا قيم tokens. سبب الاختبار: شكوى أن الحجم «لم يتغير» — فلا نفترض، نقيس. ثم قاعدة شاملة: كل أيقونة ظاهرة حجمها من
المجموعة المعتمدة فقط (لا `size={16}` يتسرّب من TSX في أي موضع)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from tests import factories as f
from tests.ui_support import _composer, _open_tab, journal_page, live_server, qa_identity  # noqa: F401

ALLOWED = {29, 32, 35, 38, 45}  # tokens ×١٫٦ (٢٠٢٦-١٠-٠٣): sm 29 · md 32 · tab 35 · list/bar 38 · rail 45

SIZES_JS = """(sel) => [...document.querySelectorAll(sel)].filter(s => s.getBoundingClientRect().width)
  .map(s => Math.round(s.getBoundingClientRect().width * 10) / 10)"""
ALL_JS = """() => [...document.querySelectorAll('svg')].filter(s => s.getBoundingClientRect().width).map(s => {
  const w = Math.round(s.getBoundingClientRect().width * 10) / 10; const chain = []; let e = s.parentElement;
  for (let i = 0; i < 3 && e; i++, e = e.parentElement) chain.push(e.tagName.toLowerCase() + '.' + String(e.getAttribute('class') || '').split(' ').join('.'));
  return [w, s.getAttribute('class'), chain.join(' < ')]; })"""


def _shot(pg, name):
    out = os.environ.get("ICON_SHOTS_DIR")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(Path(out) / name))


def _post_receipt(pg):
    """قيد فعلي حتى يظهر سجل العمليات (يُنظَّف في نهاية الوحدة)."""
    pg.mode = "real"
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    _open_tab(pg, "RECEIPT")
    comp = _composer(pg)
    pg.fill("#client-search", pg.client_code)
    pg.locator(".client-result", has_text=pg.client_code).first.click()
    pg.wait_for_timeout(400)
    comp.locator("#op-amount").fill("10.00")
    comp.locator(".field", has=pg.locator("label.field-label", has_text="العملة")).locator("select").first.select_option("LYD")
    comp.locator(".field", has=pg.locator("label.field-label", has_text=re.compile(r"^\s*الموقع\s*$"))).locator("select").select_option("TRIPOLI")
    acct = comp.locator(".acct-picker")
    acct.locator("button.acct-picker-trigger").click()
    acct.locator(".acct-picker-row").filter(has_text="1101").first.click()
    with pg.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/operations/receipt")) as info:
        comp.get_by_role("button", name="حفظ وترحيل", exact=True).click()
    assert info.value.status == 201, info.value.text()
    pg.wait_for_selector(".activity-item", timeout=10000)


def test_rendered_icon_sizes_in_every_zone(journal_page):
    pg = journal_page
    _post_receipt(pg)
    pg.fill("#client-search", f"عميل غير موجود {f.uid()[:6]}")  # يُظهر زر الإضافة السريعة (زر بأيقونة)
    pg.wait_for_selector("button.client-quick-create", timeout=5000)
    _shot(pg, "journal.png")

    def sizes(sel):
        got = pg.evaluate(SIZES_JS, sel)
        assert got, f"لا أيقونة ظاهرة لـ {sel}"
        return got

    zones = {
        "الشريط الجانبي (تبويبات)": (".sidebar .seg-row-base svg", 45, 45),
        "الشريط الجانبي (زر +)": (".sidebar-center-btn svg", 45, 45),
        "تبويبات العمليات": (".operation-dock .seg-tab svg", 35, 35),
        "سجل العمليات": (".activity-panel .activity-icon svg", 38, 38),
        "الجرس": (".notif-bell-btn svg", 38, 38),
        "الشريط العلوي": (".app-topbar svg", 38, 38),
        "أزرار النماذج": ("button.client-quick-create svg", 35, 35),
    }
    table = []
    for name, (sel, lo, hi) in zones.items():
        got = sizes(sel)
        table.append((name, sel, sorted(set(got))))
        assert all(lo <= w <= hi for w in got), f"{name}: المقاس {sorted(set(got))} خارج [{lo}, {hi}] ({sel})"
    print("\n| الموضع | المحدّد | الأحجام المقاسة (px) |\n|---|---|---|")
    for name, sel, got in table:
        print(f"| {name} | `{sel}` | {got} |")


def test_every_visible_icon_size_comes_from_the_allowed_set(journal_page):
    pg = journal_page
    pg.mode = "stub"
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    _open_tab(pg, "RECEIPT")  # يظهر نموذج فيه قوائم منسدلة (أسهم select)
    pg.fill("#client-search", f"عميل غير موجود {f.uid()[:6]}")  # زر الإضافة السريعة
    pg.wait_for_timeout(700)
    stray = [row for row in pg.evaluate(ALL_JS) if row[0] not in ALLOWED]
    assert not stray, "أيقونات بحجم خارج tokens (تتسرّب من size={…} في TSX):\n" + "\n".join(map(str, stray))


def test_dashboard_card_icons_and_settings_screen(journal_page):
    pg = journal_page
    pg.mode = "stub"
    tabs = pg.locator(".sidebar .seg-row-base .seg-tab")
    tabs.nth(0).click()
    pg.wait_for_selector(".alerts-list svg", timeout=10000)
    pg.wait_for_timeout(1500)  # أنيميشن دخول البطاقات (مقياس) يُنهي قبل القياس
    got = pg.evaluate(SIZES_JS, ".alerts-list svg")
    assert got and all(w == 38 for w in got), f"بطاقات لوحة التحكم: {sorted(set(got))}"
    _shot(pg, "dashboard.png")
    tabs.nth(7).click()
    pg.wait_for_timeout(1000)
    stray = [row for row in pg.evaluate(ALL_JS) if row[0] not in ALLOWED]
    assert not stray, str(stray)
