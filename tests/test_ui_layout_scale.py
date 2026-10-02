"""مقياس الواجهة المركزي (design tokens) لا يكسر التخطيط على ثلاثة عروض (٢٠٢٦-١٠-٠٢، بلاغ مالك: النصوص والأزرار
صغيرة بالنسبة للشاشة). لكل شاشة ولكل عرض (١٣٦٦ · ١٥٣٦ · ١٩٢٠):
  · لا تمرير أفقي للصفحة، ولا عنصر يتجاوز عرض الإطار (خارج حاويات التمرير المقصودة)؛
  · الخط الأساسي ١٦px وحقول الإدخال والأزرار الأساسية ≥ ٤٤px؛
  · كل كبسولة SegmentedTabs تطابق التبويب النشط (≤ ٢px) بعد انتهاء حركة دخول الشاشة — القياس السابق بـ
    `getBoundingClientRect` كان يتأثر بـ`scale(.82)` أثناء الحركة فتبقى الكبسولة بعرض/موضع خاطئين.
"""

from __future__ import annotations

import pytest

from tests.ui_support import journal_page, live_server, qa_identity  # noqa: F401

WIDTHS = [(1366, 768), (1536, 864), (1920, 1080)]
SCREENS = [("دفتر اليومية", ".journal-col-center"), ("لوحة التحكم", ".kpi-grid"), ("العملاء", ".clients-screen"),
           ("الإعدادات", ".seg-tabs"), ("التقارير", ".seg-tabs"), ("الحسابات", ".seg-tabs")]

JS_LAYOUT = r"""() => {
  const vw = document.documentElement.clientWidth;
  const out = {vw, scrollW: document.documentElement.scrollWidth, overflow: [], small: [], pills: []};
  const scrolls = (el) => { for (let p = el.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return true; } return false; };
  document.querySelectorAll('.app-content *').forEach(el => {
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) return;
    if ((r.right > vw + 1 || r.left < -1) && !scrolls(el)) out.overflow.push(`${el.tagName}.${String(el.className).slice(0, 40)}`);
  });
  document.querySelectorAll('.app-content input:not([type=checkbox]):not([type=radio]):not([type=hidden]), .app-content select, .app-content .btn:not(.btn-sm):not(.btn-text)').forEach(el => {
    if (el.closest('.amount-entry, .date-control')) return;  // حقل داخل مجموعة أكبر (مبلغ بارز/متنقّل تاريخ) — الحاوية هي التحكّم
    const r = el.getBoundingClientRect(); if (r.height && r.height < 43.5) out.small.push(`${el.tagName}.${String(el.className).slice(0, 30)} h=${Math.round(r.height)}`);
  });
  out.fontPx = getComputedStyle(document.body).fontSize;
  document.querySelectorAll('.seg-tabs:not(.seg-tabs-rail)').forEach(tabs => {  // الشريط الجانبي: كبسولته أعرض من الزر عمداً (نتوء الاتصال بالصفحة)
    const pill = tabs.querySelector('.seg-pill'); const act = tabs.querySelector('.seg-row-base [aria-selected=true]');
    if (!pill || !act || getComputedStyle(pill).opacity === '0') return;
    const pr = pill.getBoundingClientRect(), ar = act.getBoundingClientRect();
    out.pills.push({dl: Math.abs(pr.left - ar.left), dw: Math.abs(pr.width - ar.width)});
  });
  return out;
}"""


@pytest.mark.parametrize("width,height", WIDTHS, ids=[f"{w}" for w, _ in WIDTHS])
@pytest.mark.parametrize("title,ready", SCREENS, ids=[t for t, _ in SCREENS])
def test_screen_layout_at_width(journal_page, width, height, title, ready):
    pg = journal_page
    pg.set_viewport_size({"width": width, "height": height})
    pg.click(f"button[title^='{title}']")
    pg.wait_for_selector(ready)
    pg.wait_for_timeout(900)  # انتهاء حركة دخول الشاشة (٤٢٠ms) وتحميل الخطوط
    r = pg.evaluate(JS_LAYOUT)
    assert r["scrollW"] <= r["vw"] + 1, f"{title}@{width}: تمرير أفقي للصفحة ({r['scrollW']} > {r['vw']})"
    assert not r["overflow"], f"{title}@{width}: عناصر خارج الإطار: {sorted(set(r['overflow']))[:6]}"
    assert r["fontPx"] == "16px", r["fontPx"]
    assert not r["small"], f"{title}@{width}: عناصر تحكّم أقل من ٤٤px: {r['small'][:5]}"
    for p in r["pills"]:
        assert p["dl"] <= 2 and p["dw"] <= 2, f"{title}@{width}: الكبسولة لا تطابق التبويب النشط: {p}"
