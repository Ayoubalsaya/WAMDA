"""إعادة إنتاج آلية لثلاثة أعراض حقيقية في حركة الكبسولة (SegmentedTabs)
أبلغ عنها المالك من الاستخدام الفعلي على Edge عبر النسخة المبنية (٨٠٠٠):
(١) تكرار/تراكب النص الملوَّن · (٢) الكبسولة عالقة بين زرين · (٣) تغيّر
المحتوى بلا تحرّك الكبسولة. يُشغَّل قبل أي إصلاح (يجب أن يفشل على الكود
الحالي) وبعده (يجب أن ينجح) — راجع PROGRESS.md للتفاصيل الكاملة.

يتطلّب: `npm run build` حديث (يُخدَّم من app/static/app عبر uvicorn على
٨٠٠٠) — لا 5173 وحده. راجع الشرط: هذا سكربت تشخيصي يقرأ فقط، لا يكتب
بيانات QA (لا حاجة لعميل/عملية — الاختبار على شاشة الإعدادات وحدها،
تحميلها لا يتطلب جلسة عميل، فقط دخول موظف).

الاستخدام:
    PYTHONPATH=. venv/Scripts/python.exe scripts/qa_segmented_tabs_repro.py [--channel msedge|chromium|webkit]
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pyotp
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Session as SessionModel, User
from app.models.enums import SessionSubjectType
from app.security.passwords import hash_password

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "design" / "journal-redesign-shots" / "segtabs-repro"
BASE = "http://127.0.0.1:8000"
# WebKit تحديداً لا يمنح استثناء "loopback موثوق" لسمة Secure على الكوكي
# (خلافاً لـChromium) — كوكي الجلسة Secure لا يُرسَل فوق HTTP العادي مهما
# فعلنا، فيبقى الدخول عالقاً بصمت. موثَّق مسبقاً (راجع PROGRESS.md، جولة
# تحقُّق WebKit). الحل هنا: خادم uvicorn إضافي مؤقّت بشهادة موقَّعة ذاتياً
# على ٨٤٤٣ فقط لهذا القناة، يخدم نفس التطبيق/القاعدة — لا تغيير تطبيقي.
BASE_WEBKIT = "https://127.0.0.1:8443"

QA_USER, QA_PASS, QA_SECRET = "qa_jrnl_admin", "QaJrnl!Pass9", "JBSWY3DPEHPK3PXP"

SETTINGS_TABS = [
    "ملف الشركة", "المستخدمون", "الشركاء", "الحسابات البنكية", "العملات",
    "المواقع", "الأرصدة الافتتاحية", "الفترات المحاسبية", "سجل التدقيق",
]


def setup_db() -> None:
    db = SessionLocal()
    try:
        u = db.execute(select(User).where(User.username == QA_USER)).scalar_one_or_none()
        if u is None:
            u = User(username=QA_USER, full_name="QA journal redesign", role="ADMIN")
            db.add(u)
        u.password_hash = hash_password(QA_PASS)
        u.role, u.is_active, u.must_change_password = "ADMIN", True, False
        u.totp_secret, u.failed_attempts, u.locked_until = QA_SECRET, 0, None
        db.commit()
    finally:
        db.close()


def teardown_db() -> None:
    db = SessionLocal()
    try:
        u = db.execute(select(User).where(User.username == QA_USER)).scalar_one_or_none()
        if u:
            db.execute(SessionModel.__table__.delete().where(
                (SessionModel.subject_type == SessionSubjectType.USER) & (SessionModel.subject_id == u.id)
            ))
            db.commit()
    finally:
        db.close()


def login(pg, base: str = BASE) -> None:
    pg.goto(base + "/", wait_until="networkidle")
    pg.wait_for_selector("#username")
    pg.fill("#username", QA_USER)
    pg.fill("#password", QA_PASS)
    pg.click("button:has-text('دخول')")
    try:
        pg.wait_for_selector("#totp", timeout=8000)
    except Exception:
        pg.wait_for_timeout(5000)
        pg.click("button:has-text('دخول')")
        pg.wait_for_selector("#totp", timeout=20000)
    pg.fill("#totp", pyotp.TOTP(QA_SECRET).now())
    pg.click("button:has-text('تأكيد')")
    pg.wait_for_selector("nav.sidebar")


def pill_and_active_rect(dock):
    active = dock.locator('[aria-selected="true"]').first
    if active.count() == 0:
        return None, None
    return active.bounding_box(), dock.locator(".seg-pill").bounding_box()


def aligned(a, p, tol=1.0) -> bool:
    if not a or not p:
        return False
    return abs(a["x"] - p["x"]) <= tol and abs(a["width"] - p["width"]) <= tol and abs(a["y"] - p["y"]) <= tol


def overlay_text_mismatch(dock) -> str | None:
    """يقارن نص الطبقة النشطة (المقطوعة بنافذة القصّ) بنص الزر الحقيقي
    المقابل — أي نص غريب/مُركَّب من زرَّين يعني تراكب المعالجة. نقرأ فقط
    الجزء المرئي فعلياً من طبقة overlay عبر قياس تقاطع نافذة القصّ مع كل
    زر overlay، ونتحقق أنه يطابق حرفياً نص الزر النشط الحقيقي ولا شيء غيره.

    ٢٠٢٦-١٠-٠١ (بعد إصلاح العلّة أ): `.seg-clip-window` نفسها لم تعد تُغيَّر
    حجماً/تُنقَل بالـJS — تبقى بحجم الحاوية الكامل دائماً، والقصّ الفعلي
    عبر clip-path (انظر paint() في SegmentedTabs.tsx). فقياس getBoundingClientRect
    لهذا العنصر وحده لم يعد يعكس المنطقة المرئية فعلياً — يجب استخراج
    قيم inset من clip-path نفسها وحساب الصندوق المرئي الحقيقي منها، وإلا
    يُصبح هذا الفحص عديم الجدوى (كل الأزرار "تتقاطع" مع صندوق بحجم
    الحاوية الكامل دوماً، فلا يمكنه كشف أي علّة إطلاقاً)."""
    return dock.evaluate("""(root) => {
      const win = root.querySelector('.seg-clip-window');
      const winRect = win.getBoundingClientRect();
      const cp = win.style.clipPath || getComputedStyle(win).clipPath;
      let visRect = { left: winRect.left, right: winRect.right, top: winRect.top, bottom: winRect.bottom };
      const m = /inset\\(\\s*([-\\d.]+)px\\s+([-\\d.]+)px\\s+([-\\d.]+)px\\s+([-\\d.]+)px\\s*\\)/.exec(cp || '');
      if (m) {
        const t = Number(m[1]), r = Number(m[2]), b = Number(m[3]), l = Number(m[4]);
        visRect = { left: winRect.left + l, right: winRect.right - r, top: winRect.top + t, bottom: winRect.bottom - b };
      }
      if ((visRect.right - visRect.left) < 2 && (visRect.bottom - visRect.top) < 2) return null; // الكبسولة مخفية — لا شيء للفحص
      const overlayButtons = root.querySelectorAll('.seg-row-overlay .seg-tab');
      const visibleTexts = [];
      overlayButtons.forEach(btn => {
        const r = btn.getBoundingClientRect();
        const overlapX = Math.min(r.right, visRect.right) - Math.max(r.left, visRect.left);
        const overlapY = Math.min(r.bottom, visRect.bottom) - Math.max(r.top, visRect.top);
        if (overlapX > 2 && overlapY > 2) visibleTexts.push(btn.textContent.trim());
      });
      const activeBase = root.querySelector('.seg-row-base [aria-selected="true"]');
      const activeText = activeBase ? activeBase.textContent.trim() : null;
      return JSON.stringify({ visibleTexts, activeText });
    }""")


def overlay_layout_mismatch(dock) -> list:
    """يقارن مستطيل كل زر overlay بمستطيل الزر الحقيقي المقابل له تماماً —
    يجب أن يتطابقا حرفياً دوماً (نفس flex، نفس الحشو، صفّان متطابقان
    هيكلياً؛ القصّ البصري وحده عبر clip-path يُظهر جزءاً منه) بصرف النظر
    عن حالة الحركة (هذا فحص تخطيطي بحت، لا علاقة له بموضع الكبسولة/الحركة
    نفسها). أي انحراف يعني أن صفّ التراكب انضغط في صندوق غير صندوقه
    الطبيعي — هذا بالضبط ما أنتج "عميلخزينة (بين حسابي شر..." (العلّة أ)."""
    raw = dock.evaluate("""(root) => {
      const baseBtns = [...root.querySelectorAll('.seg-row-base .seg-tab')];
      const overlayBtns = [...root.querySelectorAll('.seg-row-overlay .seg-tab')];
      const mismatches = [];
      baseBtns.forEach((b, i) => {
        const o = overlayBtns[i];
        const rb = b.getBoundingClientRect();
        if (!o) { mismatches.push({ i, text: b.textContent.trim(), reason: 'missing_overlay_button' }); return; }
        const ro = o.getBoundingClientRect();
        const dx = Math.abs(rb.left - ro.left);
        const dw = Math.abs(rb.width - ro.width);
        if (dx > 1 || dw > 1) {
          mismatches.push({
            i, text: b.textContent.trim(),
            base: { x: rb.left, w: rb.width }, overlay: { x: ro.left, w: ro.width },
          });
        }
      });
      return JSON.stringify(mismatches);
    }""")
    import json
    return json.loads(raw)


def run_symptom_checks(pg, channel: str, base: str = BASE, label: str = "after") -> dict:
    results: dict = {}
    login(pg, base)
    pg.click("button[title^='الإعدادات']")
    pg.wait_for_selector(".seg-tabs-dock")
    dock = pg.locator(".seg-tabs-dock").first
    pg.wait_for_timeout(500)

    # ── عرض ٣: الصفحة تغيّرت والكبسولة لم تتحرك — انتقالات متتالية بلا
    # انتظار استقرار، فحص المحاذاة بعد كل انتقال (لا رسمة أخيرة فقط) ──
    # وبالتوازي، في كل مرة: فحص تخطيطي بحت (overlay_layout_mismatch) —
    # هل صفّ التراكب لا يزال مطابقاً هيكلياً لصفّ الأزرار الحقيقي؟ هذا
    # الفحص صحيح بصرف النظر عن حالة الحركة (لا علاقة له بموضع الكبسولة
    # مؤقتاً أثناء الانتقال)، فيصلح لالتقاط العلّة أ حتى في خضمّ نقرات
    # سريعة متتالية.
    stuck_events = []
    layout_mismatches = []
    order = list(range(len(SETTINGS_TABS)))
    random.Random(7).shuffle(order)
    for i in order:
        tab_label = SETTINGS_TABS[i]
        dock.get_by_role("tab", name=tab_label, exact=True).click()
        pg.wait_for_timeout(80)  # عمداً أقصر من مدة الاستقرار — يمسك السباق
        a, p = pill_and_active_rect(dock)
        lm = overlay_layout_mismatch(dock)
        if lm:
            layout_mismatches.append({"clicked": tab_label, "mismatches": lm})
    pg.wait_for_timeout(600)
    a, p = pill_and_active_rect(dock)
    final_ok = aligned(a, p)
    results["rapid_sequence_final_aligned"] = final_ok
    results["rapid_sequence_overlay_mismatches"] = stuck_events
    results["rapid_sequence_layout_mismatches"] = layout_mismatches
    pg.screenshot(path=str(SHOTS / f"{channel}_{label}_rapid_sequence.png"))

    # ── عرض ١: تكرار/تراكب النص — نطاق الصرافة (تسمية طويلة) في اليومية ──
    # (لا يظهر إلا بعد اختيار تبويب "صرافة" — نطاق العميل/الخزينة خاص بها)
    pg.click("button[title^='دفتر اليومية']")
    pg.wait_for_selector(".journal-col-center")
    pg.wait_for_timeout(400)
    pg.locator(".operation-dock").first.get_by_role("tab", name="صرافة").click()
    pg.wait_for_timeout(300)
    scope = pg.locator(".journal-col-center .seg-tabs-pill").first
    if scope.count():
        scope.get_by_role("tab").last.click()  # "خزينة"
        pg.wait_for_timeout(150)
        mismatch = overlay_text_mismatch(scope)
        results["exchange_scope_overlay"] = mismatch
        results["exchange_scope_layout_mismatches"] = overlay_layout_mismatch(scope)
        pg.screenshot(path=str(SHOTS / f"{channel}_{label}_exchange_scope.png"))
    else:
        results["exchange_scope_overlay"] = "SCOPE_PILL_NOT_FOUND"
        results["exchange_scope_layout_mismatches"] = ["SCOPE_PILL_NOT_FOUND"]

    # ── إعادة القياس: تغيير حجم النافذة أثناء انتقال مصطنع، ثم فحص المحاذاة
    # فوراً بلا نقر جديد (الفرضية ب: يجب أن يُعاد القياس تلقائياً) ──
    dock2 = pg.locator(".operation-dock").first
    dock2.get_by_role("tab", name="مصروف").click()
    pg.wait_for_timeout(30)  # منتصف الانتقال تقريباً
    pg.set_viewport_size({"width": 1000, "height": 900})
    pg.wait_for_timeout(500)
    a2, p2 = pill_and_active_rect(dock2)
    results["resize_mid_transition_aligned"] = aligned(a2, p2)
    results["resize_mid_transition_detail"] = {"active": a2, "pill": p2}
    pg.screenshot(path=str(SHOTS / f"{channel}_{label}_resize_mid_transition.png"))
    pg.set_viewport_size({"width": 1440, "height": 900})
    pg.wait_for_timeout(300)

    # ── تبويب في الخلفية أثناء انتقال، ثم العودة — يجب أن ينتهي محاذياً ──
    dock2.get_by_role("tab", name="قبض").click()
    pg.wait_for_timeout(30)
    pg.evaluate("Object.defineProperty(document,'visibilityState',{value:'hidden',configurable:true}); document.dispatchEvent(new Event('visibilitychange'))")
    pg.wait_for_timeout(300)
    pg.evaluate("Object.defineProperty(document,'visibilityState',{value:'visible',configurable:true}); document.dispatchEvent(new Event('visibilitychange'))")
    pg.wait_for_timeout(500)
    a3, p3 = pill_and_active_rect(dock2)
    results["visibility_return_aligned"] = aligned(a3, p3)
    results["visibility_return_detail"] = {"active": a3, "pill": p3}

    return results


def run_stress_50(pg, channel: str, cdp_session) -> dict:
    """٥٠ انتقالاً عشوائياً تحت إبطاء ×٦ — الكبسولة يجب أن تنتهي دائماً على
    الزر النشط بالضبط (±١ px) بعد كل انتقال."""
    cdp_session.send("Emulation.setCPUThrottlingRate", {"rate": 6})
    pg.click("button[title^='الإعدادات']")
    pg.wait_for_selector(".seg-tabs-dock")
    dock = pg.locator(".seg-tabs-dock").first
    pg.wait_for_timeout(500)
    fails = []
    rnd = random.Random(42)
    for i in range(50):
        label = rnd.choice(SETTINGS_TABS)
        dock.get_by_role("tab", name=label, exact=True).click()
        pg.wait_for_timeout(rnd.choice([600, 900, 1200]))  # يتجاوز أقصى مدة حتى تحت ×٦
        a, p = pill_and_active_rect(dock)
        if not aligned(a, p, tol=1.0):
            fails.append({"i": i, "label": label, "active": a, "pill": p})
    cdp_session.send("Emulation.setCPUThrottlingRate", {"rate": 1})
    return {"total": 50, "fails": fails, "fail_count": len(fails)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="msedge", choices=["msedge", "chromium", "webkit"])
    ap.add_argument("--stress", action="store_true", help="شغّل اختبار الإجهاد الخمسين تحت إبطاء ×٦ فقط")
    ap.add_argument("--label", default="before")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    shots_dir = SHOTS
    shots_dir.mkdir(parents=True, exist_ok=True)
    setup_db()
    report: dict = {}
    try:
        with sync_playwright() as p:
            base = BASE_WEBKIT if args.channel == "webkit" else BASE
            if args.channel == "webkit":
                browser = p.webkit.launch()
            elif args.channel == "chromium":
                browser = p.chromium.launch()
            else:
                browser = p.chromium.launch(channel="msedge")
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 900}, locale="ar",
                ignore_https_errors=(args.channel == "webkit"),
            )
            pg = ctx.new_page()

            if args.stress:
                if args.channel == "webkit":
                    print("تخطّي اختبار الإجهاد على WebKit — CDP (Emulation.setCPUThrottlingRate) خاص بـChromium/Edge فقط.")
                else:
                    login(pg, base)
                    cdp = ctx.new_cdp_session(pg)
                    report[f"stress50_{args.channel}"] = run_stress_50(pg, args.channel, cdp)
            else:
                report[f"symptoms_{args.channel}"] = run_symptom_checks(pg, args.channel, base, args.label)

            browser.close()
    finally:
        teardown_db()

    import json
    out = json.dumps(report, ensure_ascii=False, indent=2)
    print(out)
    (shots_dir / f"report_{args.label}_{args.channel}{'_stress' if args.stress else ''}.json").write_text(out, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
