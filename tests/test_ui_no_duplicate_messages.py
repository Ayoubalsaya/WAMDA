"""لا رسالة/تلميح يتكرر حرفياً في النموذج نفسه (٢٠٢٦-١٠-٠٢، ملاحظة مالك): في نموذج القبض كانت
«اختر العملة والموقع أولاً» تظهر مرتين — داخل حقل «الحساب المستقبِل» وتحته. الاختبار يفتح كل تبويب
(وكل نطاق صرافة) ويفحص نصوص الورقات المرئية في عمود النموذج: أي نص بطول ≥ ١٢ حرفاً يتكرر داخل **الحقل الواحد** يفشل (حقلان مختلفان قد يقولان «اختر العملة أولاً» كلٌّ لنفسه)."""

from __future__ import annotations

import re

import pytest

from tests.ui_support import NEEDS_CLIENT, _composer, _open_tab, _select_client, journal_page, live_server, qa_identity  # noqa: F401

SCENARIOS = [
    ("RECEIPT", None), ("PAYMENT", None), ("EXCHANGE", "CLIENT"), ("EXCHANGE", "TREASURY"),
    ("CASH_TRANSFER", None), ("REMIT_OUT", None), ("EXPENSE", None), ("SWIFT_OUT", None), ("SWIFT_IN", None),
    ("SWIFT_RETURN", None), ("LOCAL_MOVE", None), ("OPENING", None), ("ADJUSTMENT", None),
]

JS_FIELD_DUPLICATES = r"""
root => {
  const dups = [];
  const leaves = (el, out) => {
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || el.getAttribute('aria-hidden') === 'true') return;
    if (['SCRIPT', 'STYLE', 'OPTION', 'SELECT'].includes(el.tagName)) return;
    const kids = Array.from(el.children);
    if (kids.length === 0) {
      const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
      if (t) out.push(t);
    } else kids.forEach(k => leaves(k, out));
  };
  // نطاق الفحص: كل حقل `.field` وكل `.form-guide` على حدة — الرسالة نفسها مرتين داخل حقل واحد هي العيب
  root.querySelectorAll('.field, .form-guide').forEach(box => {
    const out = [];
    leaves(box, out);
    const long = out.filter(t => t.length >= 12);
    new Set(long.filter(t => long.filter(x => x === t).length > 1)).forEach(t => dups.push(t));
  });
  return dups;
}
"""


@pytest.mark.parametrize("op,scope", SCENARIOS, ids=[f"{o}-{s}" if s else o for o, s in SCENARIOS])
@pytest.mark.parametrize("with_client", [False, True], ids=["no-client", "client"])
def test_no_message_repeated_within_the_composer(journal_page, op, scope, with_client):
    pg = journal_page
    pg.mode = "stub"
    # بلا عميل أولاً (حالة «اختر … أولاً» الأكثر ظهوراً) ثم بعميل
    pg.reload(wait_until="networkidle")
    pg.wait_for_selector(".journal-col-center")
    _open_tab(pg, op)
    if with_client and op in NEEDS_CLIENT:
        _select_client(pg)
    if scope == "TREASURY":
        _composer(pg).locator("button").filter(has_text="خزينة").first.click()
        pg.wait_for_timeout(300)
    repeated = sorted(set(_composer(pg).locator(".composer-panel").evaluate(JS_FIELD_DUPLICATES)))
    assert not repeated, f"{op}/{scope}: نص مكرَّر داخل الحقل الواحد: {repeated}"
