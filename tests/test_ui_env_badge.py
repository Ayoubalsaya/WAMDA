"""علامة البيئة في الواجهة (٢٠٢٦-١٠-١٢): شريط + شارة + بادئة العنوان، لا تعترض النقر ولا تزيح التخطيط، وكوكي CSRF يُقرأ باسم البيئة."""

from __future__ import annotations

from tests.ui_support import journal_page, live_server, qa_identity  # noqa: F401  (الـfixtures تُلتقَط بالاسم)


def test_env_badge_visible_title_prefixed_and_non_blocking(journal_page):
    pg = journal_page
    badge = pg.locator('[data-testid="env-badge"]')
    assert badge.count() == 1
    assert badge.get_attribute("data-env") == "local"
    assert "تطوير" in badge.inner_text() and "بيانات تجريبية" in badge.inner_text()
    assert pg.title().startswith("[تطوير]")
    events = pg.evaluate(
        "() => Array.from(document.querySelectorAll('[data-testid=\"env-badge\"] > div')).map(d => getComputedStyle(d).pointerEvents)"
    )
    assert events and all(e == "none" for e in events)
    pos = pg.evaluate(
        "() => Array.from(document.querySelectorAll('[data-testid=\"env-badge\"] > div')).map(d => getComputedStyle(d).position)"
    )
    assert all(p == "fixed" for p in pos)  # لا تزيح التخطيط
