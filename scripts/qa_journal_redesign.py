"""QA حيّ لشاشة دفتر اليومية (إعادة التصميم — docs/design/journal-redesign-plan.md).

يُشغَّل مرتين بالتطابق: `--label before` قبل أي تعديل بصري، ثم `--label after`.
لكل نوع من الاثني عشر: يملأ النموذج فعلياً عبر الواجهة، يلتقط لقطة، ويُرحِّل
(ما لم يُمرَّر `--no-post`). في النهاية يعكس كل ما رحّله (LIFO) عبر
`POST /operations/{id}/cancel` — الحذف المباشر محظور بمشغّل قاعدة البيانات.

بيانات QA بالسابقة الموحَّدة: مستخدم `qa_jrnl_admin` · عميل `QA-JRNL-001`
(انظر app/cli/purge_demo_data.py). لا يُنشئ أي حساب/عملة جديدة — يستعمل
حسابات البذر القائمة فقط.

الاستخدام (الواجهة عبر vite على 5173 والخادم على 8000 — تحقَّق أن الخادم
يخدم الكود الحالي قبل التشغيل، انظر PROGRESS.md «قواعد ثابتة»):
    PYTHONPATH=. venv/Scripts/python.exe scripts/qa_journal_redesign.py --label before
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pyotp
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Client, Session as SessionModel, User
from app.models.enums import SessionSubjectType
from app.security.passwords import hash_password

QA_USER, QA_PASS, QA_SECRET = "qa_jrnl_admin", "QaJrnl!Pass9", "JBSWY3DPEHPK3PXP"
QA_CLIENT_CODE, QA_CLIENT_NAME = "QA-JRNL-001", "عميل QA — دفتر اليومية"
ROOT = Path(__file__).resolve().parent.parent
TYPES = [
    "OPENING", "RECEIPT", "PAYMENT", "EXCHANGE", "CASH_TRANSFER", "REMIT_OUT", "EXPENSE",
    "SWIFT_OUT", "SWIFT_IN", "SWIFT_RETURN", "LOCAL_MOVE", "ADJUSTMENT",
]
LEVEL2 = {"SWIFT_OUT", "SWIFT_IN", "SWIFT_RETURN", "LOCAL_MOVE", "OPENING", "ADJUSTMENT"}
TAB_LABEL = {
    "RECEIPT": "قبض", "PAYMENT": "صرف", "EXCHANGE": "صرافة", "CASH_TRANSFER": "تحويل بعمولة",
    "REMIT_OUT": "إرسال خارجي", "EXPENSE": "مصروف", "SWIFT_OUT": "سويفت خروج",
    "SWIFT_IN": "سويفت وصول", "SWIFT_RETURN": "سويفت مرتجع", "LOCAL_MOVE": "نقل داخلي",
    "OPENING": "رصيد افتتاحي", "ADJUSTMENT": "تسوية",
}


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
        c = db.execute(select(Client).where(Client.code == QA_CLIENT_CODE)).scalar_one_or_none()
        if c is None:
            c = Client(code=QA_CLIENT_CODE, name_ar=QA_CLIENT_NAME, search_name=QA_CLIENT_NAME, credit_allowed=False)
            db.add(c)
        c.is_active = True
        db.commit()
    finally:
        db.close()


def teardown_db() -> str:
    """يحذف المستخدم إن أمكن، وإلا يعطّله؛ العميل يُعطَّل دائماً (له قيود مرحّلة)."""
    db = SessionLocal()
    note = []
    try:
        u = db.execute(select(User).where(User.username == QA_USER)).scalar_one_or_none()
        if u:
            db.execute(SessionModel.__table__.delete().where(
                (SessionModel.subject_type == SessionSubjectType.USER) & (SessionModel.subject_id == u.id)
            ))
            try:
                db.delete(u)
                db.commit()
                note.append("user deleted")
            except Exception:
                db.rollback()
                u = db.execute(select(User).where(User.username == QA_USER)).scalar_one()
                u.is_active = False
                db.commit()
                note.append("user deactivated")
        c = db.execute(select(Client).where(Client.code == QA_CLIENT_CODE)).scalar_one_or_none()
        if c:
            c.is_active = False
            db.commit()
            note.append("client deactivated")
    finally:
        db.close()
    return ", ".join(note)


class Runner:
    def __init__(self, pg, shots: Path, post: bool):
        self.pg, self.shots, self.post, self.n = pg, shots, post, 0
        self.entry_nos: list[str] = []
        self.results: dict[str, str] = {}
        self.swift_out_nos: list[str] = []
        self.usd_loc = ""

    # ── مساعدات عامة ────────────────────────────────────────────────
    @property
    def composer(self):
        return self.pg.locator(".journal-col-center")

    def field(self, label: str, prefix: bool = False):
        rx = re.compile(rf"^\s*{re.escape(label)}" + ("" if prefix else r"\s*$"))
        return self.composer.locator(".field").filter(has=self.pg.locator("label.field-label", has_text=rx)).first

    def fill(self, label: str, value: str, prefix: bool = False):
        self.field(label, prefix).locator("input, textarea").first.fill(value)

    def fill_amount(self, value: str):
        """حقل المبلغ: «المبلغ المنقول» في تحويل بعمولة قبل إعادة التصميم، «المبلغ» بعده (حقل واحد)."""
        for label in ("المبلغ المنقول", "المبلغ"):
            f = self.field(label, prefix=label != "المبلغ")
            if f.count():
                f.locator("input").first.fill(value)
                return
        raise RuntimeError("لا حقل مبلغ")

    def select(self, label: str, value: str, prefix: bool = False):
        self.field(label, prefix).locator("select").select_option(value=value)

    def select_first(self, label: str, prefix: bool = False) -> str:
        sel = self.field(label, prefix).locator("select")
        self.pg.wait_for_function(
            "el => Array.from(el.options).some(o => !o.disabled && o.value)", arg=sel.element_handle(), timeout=10000)
        value = sel.evaluate("el => Array.from(el.options).find(o => !o.disabled && o.value).value")
        sel.select_option(value=value)
        return value

    def pick(self, label: str, code: str | None = None):
        f = self.field(label)
        f.locator("button.acct-picker-trigger").click()
        rows = f.locator(".acct-picker-row")
        (rows.filter(has_text=code).first if code else rows.first).click()

    def shot(self, name: str):
        self.pg.screenshot(path=str(self.shots / f"{name}.png"), full_page=True)

    def open_tab(self, op: str):
        label = TAB_LABEL[op]
        rx = re.compile(rf"^\s*{re.escape(label)}\s*$")
        btn = self.composer.locator("button").filter(has_text=rx).first
        if not btn.is_visible():
            self.composer.locator("button").filter(has_text=re.compile(r"^\s*المزيد\s*$")).first.click()
        btn.click()
        self.pg.wait_for_timeout(250)

    def select_client(self):
        self.pg.fill("#client-search", "QA-JRNL")
        self.pg.locator(".client-search-row", has_text=QA_CLIENT_CODE).first.click()
        self.pg.wait_for_timeout(400)

    def _post_and_wait(self, action):
        """ينفّذ الإجراء ويقرأ ردّ POST /operations/* الفعلي — لا نص نجاح قديماً في الصفحة."""
        def pred(r):
            return (r.request.method == "POST" and "/operations/" in r.url
                    and not r.url.endswith("/cancel") and not r.url.endswith("/edit"))
        with self.pg.expect_response(pred, timeout=20000) as ri:
            action()
        return ri.value

    def submit(self, via_enter_in: str | None = None) -> str:
        pg = self.pg
        if via_enter_in:
            action = lambda: self.field(via_enter_in, prefix=True).locator("input").first.press("Enter")  # noqa: E731
        else:
            action = lambda: self.composer.get_by_role("button", name="حفظ وترحيل", exact=True).click()  # noqa: E731
        resp = self._post_and_wait(action)
        if resp.status == 409 and "سيصبح" in resp.text():
            box = pg.locator("textarea[placeholder^='سبب تجاوز الرصيد']")
            box.fill("QA — تجاوز رصيد مقصود في اختبار الواجهة")
            btn = pg.get_by_role("button", name="تأكيد الترحيل رغم الرصيد السالب")
            resp = self._post_and_wait(btn.click)
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status}: {resp.text()[:300]}")
        no = resp.json()["entry_no"]
        self.entry_nos.append(no)
        pg.locator("text=/تم الترحيل/").first.wait_for(timeout=10000)
        return no

    def neg_margin_if_asked(self):
        f = self.composer.locator("label.field-label", has_text="سبب الهامش السالب")
        if f.count():
            self.composer.locator(".field").filter(has=f.first).locator("input").fill("QA — هامش سالب مقصود")

    # ── سيناريو كل نوع ────────────────────────────────────────────
    def fill_type(self, op: str):
        pg = self.pg
        if op == "OPENING":
            self.pick("الحساب", "1323")
            self.select("العملة", "USD")
            self.fill("المبلغ", "2000")
            self.fill("التاريخ", pg.evaluate("new Date().toISOString().slice(0,10)"), prefix=True)
            self.composer.locator("label", has_text=re.compile(r"^\s*مدين\s*$")).first.click()
            self.select("مصدر الرصيد", "VERIFIED")
            self.select("درجة الثقة", "HIGH", prefix=True)
            self.fill("ملاحظة (اختياري)", "QA افتتاحي", prefix=True)
        elif op == "RECEIPT":
            self.select("العملة", "LYD")
            self.select("الموقع", "TRIPOLI")
            self.pick("الحساب المستقبِل", "1101")
            self.fill("المبلغ", "5000")
            self.fill("ملاحظة (اختياري)", "دفعة QA", prefix=True)
        elif op == "PAYMENT":
            self.select("العملة", "LYD")
            self.select("الموقع", "TRIPOLI")
            self.pick("الحساب المصروف منه", "1101")
            self.fill("المبلغ", "500")
        elif op == "EXCHANGE":
            self.select("العملة", "USD")
            self.select("الموقع", self.usd_loc)
            self.select("إلى عملة", "LYD")
            self.select("إلى موقع", "TRIPOLI")
            self.fill("المبلغ", "100")
            self.fill("سعر العميل", "5.30")
            self.fill("سعر التكلفة", "5.40")
        elif op == "CASH_TRANSFER":
            self.select("العملة", "LYD")
            self.select("من موقع", "TRIPOLI")
            self.select("إلى موقع", "BENGHAZI", prefix=True)
            self.fill_amount("200")
            self.pick("حساب المصدر (الشركة)", "1101")
            self.pick("الحساب المنفِّذ", "1102")
            self.select("عملة العمولة", "LYD")
            self.fill("عمولة العميل", "10", prefix=True)
            self.fill("تكلفة العمولة", "5")
            self.pick("حساب تكلفة العمولة (المراسل)")
        elif op == "REMIT_OUT":
            self.select("الموقع المخصوم من العميل", self.usd_loc)
            self.pick("حساب المراسل")
            self.select("عملة المبلغ المُرسَل", "CNY")
            self.fill("المبلغ (", "300", prefix=True)
            self.fill("سعر العميل", "7.0")
            self.fill("سعر التكلفة", "7.1")
        elif op == "EXPENSE":
            self.pick("بند المصروف", "5201")
            self.select("العملة", "LYD")
            self.pick("الحساب المصروف منه", "1101")
            self.fill("المبلغ", "25")
            self.fill("البيان (إلزامي)", "QA مصروف اختبار")
        elif op == "SWIFT_OUT":
            self.pick("حساب المراسل (تركيا)", "1323")
            self.fill("المبلغ (USD)", "300")
            self.fill("مرجع خارجي (اختياري)", "QA-SW")
        elif op == "SWIFT_IN":
            self.select("الحركة المعلَّقة (أُرسلت ولم تُستقبَل بعد)", self._movement_value(self.swift_out_nos[0]))
            self.fill("المبلغ الواصل", "300")
            self.fill("الرسوم الفعلية", "3")
            self.fill("سعر تحويل البنك للرمبي (اختياري)", "7.1")
            self.pick("الحساب المستقبِل", "1403")
        elif op == "SWIFT_RETURN":
            self.select("الحركة المعلَّقة المطلوب ارتجاعها", self._movement_value(self.swift_out_nos[1]))
            self.fill("المبلغ المرتجع كاملاً", "300")
            self.fill("رسوم على العميل", "3")
            self.select("موقع العميل", self.usd_loc)
        elif op == "LOCAL_MOVE":
            self.select("العملة", "LYD")
            self.pick("من حساب", "1101")
            self.pick("إلى حساب", "1103")
            self.fill("المبلغ", "100")
            self.fill("رسوم (اختياري", "1", prefix=True)
        elif op == "ADJUSTMENT":
            self.pick("الحساب", "1101")
            self.select("العملة", "LYD")
            self.fill("المبلغ", "10")
            self.composer.locator("label", has_text="زيادة في الصندوق").first.click()
            self.fill("السبب (إلزامي)", "QA تسوية اختبار")

    def _movement_value(self, entry_no: str) -> str:
        sel = self.field("الحركة المعلَّقة", prefix=True).locator("select")
        self.pg.wait_for_function(
            "([el, no]) => Array.from(el.options).some(o => o.textContent.includes(no))",
            arg=[sel.element_handle(), entry_no], timeout=10000)
        return sel.evaluate(
            "(el, no) => Array.from(el.options).find(o => o.textContent.includes(no)).value", entry_no)

    def run_type(self, op: str):
        pg = self.pg
        try:
            self.open_tab(op)
            self.fill_type(op)
            if op in {"EXCHANGE", "REMIT_OUT"}:
                pg.wait_for_timeout(300)
                self.neg_margin_if_asked()
            pg.wait_for_timeout(300)
            self.shot(op)
            if not self.post:
                self.results[op] = "filled (no post)"
                return
            no = self.submit(via_enter_in="المبلغ" if op == "RECEIPT" else None)
            if op == "SWIFT_OUT":
                self.swift_out_nos.append(no)
            self.results[op] = f"POSTED {no}"
        except Exception as e:  # noqa: BLE001 — نُسجّل ونكمل بقية الأنواع
            self.results[op] = f"FAIL: {str(e)[:300]}"
            try:
                self.shot(f"{op}_FAILED")
            except Exception:
                pass


def orphan_entry_nos() -> list[str]:
    """قيود QA مرحَّلة بقيت من تشغيل انهار قبل العكس (بحسب المنشئ أو العميل) — تُعكس مع هذا التشغيل."""
    from sqlalchemy import text

    db = SessionLocal()
    try:
        rows = db.execute(text(
            "select e.entry_no from journal_entries e "
            "left join clients c on c.id = e.client_id left join users u on u.id = e.created_by "
            "where e.status = 'POSTED' and e.reverses_entry_id is null "
            "and (c.code = :c or u.username = :u) order by e.id"
        ), {"c": QA_CLIENT_CODE, "u": QA_USER}).all()
        return [r[0] for r in rows]
    finally:
        db.close()


def cancel_all(pg, entry_nos: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    ids = pg.evaluate("""async (nos) => {
      const today = new Intl.DateTimeFormat('en-CA', {timeZone:'Africa/Tripoli'}).format(new Date());
      const r = await fetch('/journal/entries?date=' + today + '&include_reversed=false', {credentials:'include'});
      const rows = await r.json();
      const m = {}; for (const e of rows) m[e.entry_no] = e.id; return m;
    }""", entry_nos)
    for no in reversed(entry_nos):
        eid = ids.get(no)
        if eid is None:
            out[no] = "id not found"
            continue
        res = pg.evaluate("""async (id) => {
          const csrf = decodeURIComponent((document.cookie.match(/(?:^|; )wamda_csrf=([^;]*)/)||[])[1]||'');
          const r = await fetch('/operations/' + id + '/cancel', {method:'POST', credentials:'include',
            headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body: JSON.stringify({reason:'QA — عكس قيد اختبار الواجهة'})});
          return r.status + ' ' + (await r.text()).slice(0, 160);
        }""", eid)
        out[no] = res
    return out


def run_all(runner: Runner, args, types: list[str]) -> None:
    runner.shot("00_initial_no_client")
    runner.select_client()
    runner.shot("01_client_selected")
    runner.usd_loc = "TRIPOLI"  # مسموح لعملاء USD في البذر (مع CHINA/TURKEY)
    # ترتيب التنفيذ يضمن رصيداً كافياً لكل خطوة لاحقة
    order = ["OPENING", "RECEIPT", "PAYMENT", "EXCHANGE", "CASH_TRANSFER", "REMIT_OUT", "EXPENSE",
             "SWIFT_OUT", "SWIFT_OUT", "SWIFT_IN", "SWIFT_RETURN", "LOCAL_MOVE", "ADJUSTMENT"]
    # رصيد USD للعميل لازم قبل EXCHANGE/REMIT_OUT/SWIFT_RETURN: قبض دولار إضافي
    if {"RECEIPT", "EXCHANGE", "REMIT_OUT", "SWIFT_RETURN"} & set(types):
        runner.open_tab("RECEIPT")
        runner.select("العملة", "USD")
        runner.select("الموقع", runner.usd_loc)
        runner.pick("الحساب المستقبِل")
        runner.fill("المبلغ", "800")
        if runner.post:
            runner.submit()
    seen_swift = 0
    for op in order:
        if op not in types:
            continue
        if op == "SWIFT_OUT":
            seen_swift += 1
        if op == "SWIFT_OUT" and seen_swift == 2:
            runner.open_tab("SWIFT_OUT")
            runner.fill_type("SWIFT_OUT")
            if runner.post:
                runner.swift_out_nos.append(runner.submit())
            continue
        runner.run_type(op)
    if args.extras:
        extras(runner)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--base", default="http://127.0.0.1:5173")
    ap.add_argument("--no-post", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--state", default="", help="مسار ملف جلسة Playwright لإعادة الاستخدام (يتفادى حدّ معدّل الدخول: ١٠/٥ دقائق)")
    ap.add_argument("--keep-user", action="store_true", help="لا تحذف/تعطّل مستخدم QA عند الانتهاء (مع --state)")
    ap.add_argument("--cleanup-only", action="store_true", help="اعكس قيود QA اليتيمة فقط")
    ap.add_argument("--extras", action="store_true", help="لقطات إضافية: معالج · تعديل · صف موسّع · نطاق خزينة")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    shots = ROOT / "docs" / "design" / "journal-redesign-shots" / args.label
    shots.mkdir(parents=True, exist_ok=True)
    setup_db()
    types = [t for t in TYPES if not args.only or t in args.only.split(",")]
    runner: Runner | None = None
    cancel_report: dict[str, str] = {}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            state = Path(args.state) if args.state else None
            ctx = b.new_context(
                viewport={"width": 1440, "height": 1500}, ignore_https_errors=True,
                storage_state=str(state) if state and state.exists() else None)
            pg = ctx.new_page()
            pg.goto(args.base + "/", wait_until="networkidle")
            if not pg.locator("nav.sidebar").count():
                pg.wait_for_selector("#username")
                pg.fill("#username", QA_USER)
                pg.fill("#password", QA_PASS)
                pg.click("button:has-text('دخول')")
                pg.wait_for_selector("#totp", timeout=20000)
                pg.fill("#totp", pyotp.TOTP(QA_SECRET).now())
                pg.click("button:has-text('تأكيد')")
                pg.wait_for_selector("nav.sidebar")
                if state:
                    ctx.storage_state(path=str(state))
            pg.click("button[title^='دفتر اليومية']")
            pg.wait_for_selector(".journal-col-center")
            pg.wait_for_timeout(800)
            runner = Runner(pg, shots, post=not args.no_post or args.cleanup_only)
            runner.entry_nos.extend(orphan_entry_nos())
            try:
                if not args.cleanup_only:
                    run_all(runner, args, types)
            finally:
                if runner.post and runner.entry_nos:
                    cancel_report = cancel_all(pg, runner.entry_nos)
            b.close()
    finally:
        td = "kept" if args.keep_user else teardown_db()
    report = {"label": args.label, "results": runner.results if runner else {}, "entries": runner.entry_nos if runner else [],
              "cancel": cancel_report, "teardown": td}
    (shots / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    bad = [k for k, v in report["results"].items() if v.startswith("FAIL")]
    return 1 if bad else 0


def extras(r: Runner):
    """لقطات إضافية للعناصر المدمجة: معالج الخطوتين · صف السجل الموسّع · نافذة التعديل · نطاق الخزينة."""
    pg = r.pg
    r.open_tab("EXCHANGE")
    r.composer.locator("button").filter(has_text="خزينة").first.click()
    pg.wait_for_timeout(300)
    r.shot("X_exchange_treasury_scope")
    r.open_tab("RECEIPT")
    pg.locator("button", has_text="معالج الخطوتين").first.click()
    pg.wait_for_timeout(500)
    r.shot("X_wizard_step1")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    if pg.locator(".modal-veil, .wizard-panel, .modal-backdrop").count():
        pg.locator(".wizard-close, .modal-close").first.click()
    rows = pg.locator(".today-op-summary, .activity-item")
    if rows.count():
        rows.first.click()
        pg.wait_for_timeout(300)
        r.shot("X_log_row_expanded")
        edit = pg.get_by_role("button", name=re.compile("تعديل")).first
        if edit.count():
            edit.click()
            pg.wait_for_timeout(600)
            r.shot("X_edit_mode_modal")


if __name__ == "__main__":
    raise SystemExit(main())
