"""حارس انحدار دائم (٢٠٢٦-٠٩-٢٥) — يمنع تكرار الصنف الذي كشفته ثلاثة
تثبيتات يدوية سابقة (`CurrencyBadge.tsx`/`parseSearchQuery.ts`/
`OpeningBalancesTab.tsx`): كود حيّ (لا تعليق ولا docstring) يذكر كود
عملة أو موقع **حرفياً** بدل جلبه من القاعدة (`/reference/currencies`،
`/reference/locations`) — أي قائمة أو شرط كهذا يفترض عدد العملات/المواقع
الحالي بصمت، فيتعطّل تلقائياً عند إضافة عملة/موقع رابع أو خامس بلا أي
خطأ واضح وقت الإضافة، يُكتشف فقط صدفةً أثناء تحقُّق حيّ لاحق.

**الفحص**: حرفي مُقتبَس كامل (`'CNY'`/`"TURKEY"`) أو مفتاح كائن TS غير
مُقتبَس (`CNY:`) لأي من الأكواد المعروفة، خارج التعليقات/الـdocstrings،
في أي ملف مصدر Python (`app/`) أو TypeScript (`frontend/src/`).

**الاستثناءات** (`ALLOWED_LITERAL_FILES` أدناه) قواعد عمل موثَّقة
فُحصت يدوياً وأثبتت أنها ليست افتراض "العدد الحالي" — إضافة ملف جديد
للاستثناء يحتاج نفس الفحص اليدوي، لا إعفاءً تلقائياً لمجرد الإضافة هنا.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CURRENCY_CODES = ("LYD", "USD", "CNY")
LOCATION_CODES = ("TRIPOLI", "BENGHAZI", "LIBYA_BANK", "TURKEY", "CHINA")
ALL_CODES = CURRENCY_CODES + LOCATION_CODES
_CODES_ALT = "|".join(ALL_CODES)

# حرفي مُقتبَس كامل (كود بايثون/TS حقيقي) أو مفتاح كائن TS غير مُقتبَس
# (نمط `{ CNY: ... }` — بالضبط ما كسر CurrencyBadge.tsx سابقاً).
LITERAL_RE = re.compile(rf"""['"]({_CODES_ALT})['"]|\b({_CODES_ALT})\s*:(?!:)""")

# انظر توثيق كل استثناء في PROGRESS.md دفعة ٢٠٢٦-٠٩-٢٥ ("افحص الصنف كاملاً").
ALLOWED_LITERAL_FILES: dict[str, str] = {
    "app/cli/seed.py":
        "مصدر بيانات التهيئة الأساسي نفسه — البذر الأول، لا منطق تشغيلي يفترض عدداً",
    "app/engine/operations/exchange.py":
        "execute_via_lot مخصَّص حصراً لرمبي مخزون السويفت §٢-٨-ج (توثَّق acceptance(48))، ليس افتراضاً عاماً",
    "app/engine/operations/swift_in.py":
        "نفس مسار رمبي مخزون السويفت §٢-٨-ج أعلاه — SWIFT_IN تحديداً",
    "app/engine/account_filters.py":
        "SWIFT_OUT/SWIFT_IN مُعرَّفان بموقع ثابت (تركيا/الصين) §٤ رقم ٦ — تعريف العملية نفسه لا خيار قابل للتغيير",
    "app/routers/dashboard.py":
        "مراسلو تركيا/بنوك الصين §٧-٧ تقريران مُسمَّيان بالاسم صراحةً، لا تجميع عام لكل المواقع",
    "app/documents/reports_doc.py":
        "تقرير ربحية دفعات الرمبي — نفس مسار السويفت §٢-٨-ج أعلاه",
    "frontend/src/lib/fxPreview.ts":
        "PIVOT_CODE=USD قرار معماري دائم — schemas/settings.py: عملة محورية واحدة لا تتغيَّر من شاشة الإعدادات",
    "frontend/src/lib/parseSearchQuery.ts":
        "FALLBACK_CURRENCIES احتياطي موثَّق فقط لحين توفر knownCurrencies الحيّة من الخادم، لا قائمة نهائية",
    "frontend/src/components/CurrencyBadge.tsx":
        "SYMBOLS/CLASS خرائط عرض بها fallback صريح (badge-other) لأي كود غير معروف — لا تفترض عدم وجود عملة خامسة",
    "frontend/src/screens/journal/ExchangeWizard.tsx":
        "LYD/CNY قيم useState ابتدائية فقط (المستخدم يغيّرها من قائمة currencies الحيّة)؛ USD للعملة المحورية الثابتة",
    "frontend/src/screens/journal/OperationForm.tsx":
        "CNY مرتبط بمسار SWIFT_IN رمبي §٢-٨-ج؛ USD للعملة المحورية الثابتة (PIVOT_CODE)",
    "frontend/src/screens/AccountsScreen.tsx":
        "شاشة دفعات الرمبي §٢-٨-ج حصراً — تبويب مخصَّص لا جدول عملات عام",
    "frontend/src/screens/ReconciliationScreen.tsx":
        "'USD' هنا placeholder نصي في حقل إدخال حر (لا يقيّد القيمة الفعلية)، لا قائمة/شرط",
}


def _strip_python_comments(text: str) -> str:
    # بسيط عمداً: يشطب من أول # غير مُقتبَس فعلياً حتى نهاية السطر. لا
    # يعالج docstrings كحالة خاصة — الفحص اللاحق يطابق حرفياً مُقتبَساً
    # بالكامل بين علامتي اقتباس متلاصقتين بالكود، وهذا لا يحدث داخل نثر
    # docstring عربي (اللصق يفصل الكود دائماً بأقواس/أسهم لا علامات اقتباس).
    lines = []
    for line in text.split("\n"):
        idx = line.find("#")
        lines.append(line if idx == -1 else line[:idx])
    return "\n".join(lines)


def _strip_ts_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    lines = []
    for line in text.split("\n"):
        idx = line.find("//")
        lines.append(line if idx == -1 else line[:idx])
    return "\n".join(lines)


def _scan_file(path: Path, *, is_python: bool) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    stripped = _strip_python_comments(text) if is_python else _strip_ts_comments(text)
    violations = []
    for lineno, line in enumerate(stripped.split("\n"), start=1):
        if LITERAL_RE.search(line):
            violations.append((lineno, line.strip()))
    return violations


def test_no_hardcoded_currency_or_location_literals_outside_allowed_files():
    candidates: list[tuple[Path, bool]] = []
    for py_file in (REPO_ROOT / "app").rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        candidates.append((py_file, True))
    for ts_file in (REPO_ROOT / "frontend" / "src").rglob("*.ts*"):
        candidates.append((ts_file, False))

    all_violations: dict[str, list[tuple[int, str]]] = {}
    for path, is_python in candidates:
        rel = path.relative_to(REPO_ROOT).as_posix()
        found = _scan_file(path, is_python=is_python)
        if found and rel not in ALLOWED_LITERAL_FILES:
            all_violations[rel] = found

    if all_violations:
        report = "\n".join(
            f"  {rel}:\n" + "\n".join(f"    سطر {n}: {snippet}" for n, snippet in hits)
            for rel, hits in sorted(all_violations.items())
        )
        raise AssertionError(
            "كود عملة/موقع مُثبَّت حرفياً خارج الملفات المسموحة — هذا بالضبط "
            "الصنف الذي كسر CurrencyBadge.tsx/parseSearchQuery.ts/OpeningBalancesTab.tsx "
            "(دفعة ٢٠٢٦-٠٩-٢٥). استبدله بجلب حيّ من /reference/currencies أو "
            "/reference/locations، أو أضِف الملف إلى ALLOWED_LITERAL_FILES هنا مع "
            "سبب موثَّق إن كان استخداماً متعمَّداً حقاً (مثل رمبي السويفت §٢-٨-ج):\n" + report
        )


def test_allowed_literal_files_still_exist():
    """الاستثناءات تشير لملفات حقيقية — ملف حُذف أو نُقل يترك سطراً ميتاً
    يُخفي تغطية الفحص أعلاه بصمت بدل رفع خطأ واضحاً."""
    missing = [rel for rel in ALLOWED_LITERAL_FILES if not (REPO_ROOT / rel).is_file()]
    assert not missing, f"ملفات مستثناة لم تعد موجودة — نظّف ALLOWED_LITERAL_FILES: {missing}"
