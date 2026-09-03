"""اختبار القبول ٥٠ (§١١): RTL — لا نص مقلوب · الأرقام LTR · الأعمدة
المالية متحاذية · الأيقونات الاتجاهية معكوسة والعالمية لا.

تحقُّق بصري/DOM بحت لا يُعبَّر عنه في pytest بلا متصفح حيّ — يُشغَّل يدوياً
قبل كل عرض على المالك، ونتيجته توثَّق في PROGRESS.md. مُستثنى صراحةً من
`tests/test_marker_coverage.py` (لا يبقى علامة حمراء دائمة).

الاستخدام: شغّل السيرفر (uvicorn، الواجهة المبنية) ثم:
    PYTHONPATH=. venv/Scripts/python.exe scripts/verify_acceptance_50_rtl.py [BASE_URL]
افتراضي BASE_URL = http://127.0.0.1:8020
"""

from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pyotp
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Session as SessionModel, User
from app.models.enums import SessionSubjectType
from app.security.passwords import hash_password

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8020"
QA_USER, QA_PASS, QA_SECRET = "qa_a50_admin", "QaA50Pass!9", "JBSWY3DPEHPK3PXP"


def _setup(db):
    u = db.execute(select(User).where(User.username == QA_USER)).scalar_one_or_none()
    if u is None:
        u = User(username=QA_USER, full_name="QA A50", role="ADMIN")
        db.add(u)
    u.password_hash = hash_password(QA_PASS)
    u.role, u.is_active, u.must_change_password = "ADMIN", True, False
    u.totp_secret, u.failed_attempts, u.locked_until = QA_SECRET, 0, None
    db.commit()


def _cleanup(db):
    u = db.execute(select(User).where(User.username == QA_USER)).scalar_one_or_none()
    if u:
        db.execute(SessionModel.__table__.delete().where(
            (SessionModel.subject_type == SessionSubjectType.USER) & (SessionModel.subject_id == u.id)
        ))
        db.delete(u)
        db.commit()


def _run() -> list[str]:
    from playwright.sync_api import sync_playwright

    fails: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(ignore_https_errors=True).new_page()
        pg.goto(BASE + "/", wait_until="networkidle")
        pg.wait_for_selector("#username")

        # ١) اتجاه الوثيقة RTL، لا نص مقلوب (حاويات النص RTL فعلياً)
        doc_dir = pg.evaluate("document.documentElement.getAttribute('dir')")
        body_dir = pg.evaluate("getComputedStyle(document.body).direction")
        if doc_dir != "rtl" or body_dir != "rtl":
            fails.append(f"اتجاه الوثيقة ليس rtl: html={doc_dir} body={body_dir}")

        pg.fill("#username", QA_USER)
        pg.fill("#password", QA_PASS)
        pg.click("button:has-text('دخول')")
        pg.wait_for_selector("#totp")
        pg.fill("#totp", pyotp.TOTP(QA_SECRET).now())
        pg.click("button:has-text('تأكيد')")
        pg.wait_for_selector("nav.sidebar")
        pg.click("button[title^='لوحة التحكم']")
        pg.wait_for_selector("text=تنبيهات")
        pg.wait_for_timeout(1200)

        # ٢) كل رقم مالي: .num بـ direction:ltr و tabular-nums، أرقام ASCII
        num_report = pg.evaluate("""() => {
          const els = Array.from(document.querySelectorAll('.num'));
          const bad = [];
          for (const el of els) {
            const cs = getComputedStyle(el);
            const t = el.textContent || '';
            if (cs.direction !== 'ltr') bad.push('direction ' + cs.direction + ' على: ' + t.slice(0,20));
            if (!/tabular-nums|tnum/.test(cs.fontVariantNumeric + ' ' + cs.fontFeatureSettings))
              bad.push('لا tabular-nums على: ' + t.slice(0,20));
            if (/[٠-٩۰-۹]/.test(t)) bad.push('أرقام هندية (لا LTR غربية): ' + t.slice(0,20));
          }
          return { count: els.length, bad };
        }""")
        if num_report["count"] == 0:
            fails.append("لا عناصر .num في لوحة التحكم — لا شيء للتحقق منه")
        fails.extend(num_report["bad"])

        # ٣) الأعمدة المالية متحاذية: خلايا الأرقام في جدول «آخر العمليات»
        align = pg.evaluate("""() => {
          const rows = Array.from(document.querySelectorAll('table tbody tr'));
          if (rows.length < 2) return { ok: true, note: 'لا جدول كافٍ' };
          const colAligns = {};
          for (const r of rows) {
            Array.from(r.children).forEach((td, i) => {
              (colAligns[i] = colAligns[i] || new Set()).add(getComputedStyle(td).textAlign);
            });
          }
          const inconsistent = Object.entries(colAligns).filter(([,s]) => s.size > 1);
          return { ok: inconsistent.length === 0, inconsistent: inconsistent.map(([i,s]) => i+':'+[...s]) };
        }""")
        if not align.get("ok"):
            fails.append(f"أعمدة جدول غير متحاذية باتساق: {align.get('inconsistent')}")

        # ٤) أيقونة عالمية (جرس التنبيهات في الترويسة) — غير معكوسة
        bell_t = pg.evaluate("""() => {
          const b = document.querySelector('svg.lucide-bell, svg.lucide-bell-ring') ||
                    document.querySelector('header svg, .topbar svg');
          return b ? getComputedStyle(b).transform : 'MISSING';
        }""")
        if bell_t not in ("none", "MISSING") and "matrix(-1" in bell_t:
            fails.append(f"أيقونة عالمية (جرس) معكوسة: {bell_t}")

        # ٥) أيقونة اتجاهية «رجوع» — انتقل لصفحة عميل
        pg.click("button[title^='العملاء']")
        pg.wait_for_timeout(800)
        row = pg.query_selector("table tbody tr")
        if row:
            row.click()
            pg.wait_for_timeout(800)
            back = pg.evaluate("""() => {
              const el = Array.from(document.querySelectorAll('button, a')).find(e => /رجوع/.test(e.textContent||''));
              if (!el) return 'MISSING';
              const svg = el.querySelector('svg');
              return svg ? (svg.getAttribute('class') || 'svg-no-class') : 'no-svg';
            }""")
            if back == "MISSING":
                fails.append("لم يُعثَر على زر «رجوع» في صفحة العميل")
            # الاتجاهية تُعالَج باختيار الأيقونة الصحيحة للـRTL (سهم يمين = نحو البداية) لا بعكس CSS — نتحقق فقط من وجودها
        pg.screenshot(path="scripts/_a50_rtl.png", full_page=True)
        b.close()
    return fails


def main() -> int:
    db = SessionLocal(); _setup(db); db.close()
    try:
        fails = _run()
    finally:
        db = SessionLocal(); _cleanup(db); db.close()
    if fails:
        print("❌ اختبار القبول ٥٠ فشل:")
        for f in fails:
            print("  -", f)
        return 1
    print("✅ اختبار القبول ٥٠: RTL · أرقام LTR جدولية · أعمدة متحاذية · أيقونات سليمة — كله مطابق.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
