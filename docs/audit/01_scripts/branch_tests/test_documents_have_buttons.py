"""حارس دائم — بالاتجاه المعاكس لـ`test_frontend_routes_exist.py`:

    كل مسار في `app/routers/documents.py` (مستند يُطبَع أو يُصدَّر
    للعميل) يجب أن يقابله زر حقيقي في الواجهة. يمنع تكرار ما وقع
    فعلاً (٢٠٢٦-٠٩-١٥): نبني مستنداً في الخادم وننساه — يعمل حين
    يُطلَب مباشرةً، لكن لا طريق للموظف يصله من الشاشة.

الأسلوب — من الخادم إلى الواجهة (مصدر الحقيقة `router.routes`، لا
قائمة يدوية تتقادم):
    · مسارات المعرّف الوحيد (`/receipt/{entry_id}.pdf` ونحوها) — يكفي
      وجود بادئة المسار الثابتة (`/documents/receipt/`) كنص حرفي في
      أي ملف واجهة؛ زر واحد يكفي كل المعرّفات الممكنة.
    · مسارات التقرير المُسمّى (`/reports/{report_key}.EXT`) — كل مفتاح
      حقيقي من `_REPORT_BUILDERS` (ولاحقة `.xlsx` فقط لمن هو في
      `_EXCEL_REPORT_KEYS`) يجب أن يكون نصاً حرفياً في الواجهة بذاته؛
      وجود شكل المسار العام لا يكفي — هذا بالضبط ما فوّت `monthly-profit`
      رغم أن `${exportKey}.pdf` كان موجوداً أصلاً بلا `exportKey` يحمل
      تلك القيمة قط.

هذا فحص خشن عمداً (وجود نصي، لا تتبع تدفّق React الكامل) — يكشف
"مستند نُسي كلياً"، وهو بالضبط ما طُلب منعه؛ الأسلاك الخاطئة (مسار
موجود لكن بفعل خاطئ، أو مبنيّ من متغيّر لا يحمل القيمة الصحيحة) يغطيها
الاختبار المعاكس `test_frontend_routes_exist.py`.
"""

from __future__ import annotations

import io
import re
from collections import defaultdict

import pytest

from app.routers import documents as documents_router

from .test_frontend_routes_exist import _FRONTEND_SRC

# كتل خرائط تصدير التقارير بحسب الامتداد — `ReportsScreen.tsx` يبني
# الرابط من متغيّر (`${exportKey}.pdf`)، فالمفتاح الحرفي لا يظهر ملتصقاً
# بالامتداد؛ لذا نقرأ *قيم* هذه الكتل تحديداً بدل البحث عن نص حر، وإلا
# يمرّ الفحص زوراً لمجرد أن نص المفتاح يظهر في مكان آخر غير متعلق
# (تسمية تبويب أو نوع `ReportId` يشتركان بنفس الحرف).
_EXPORT_MAP_BLOCKS = (("PDF_EXPORT_KEYS", "pdf"), ("EXCEL_EXPORT_KEYS", "xlsx"))


def _frontend_corpus() -> str:
    return "\n".join(
        io.open(f, encoding="utf-8").read()
        for f in [*_FRONTEND_SRC.rglob("*.ts"), *_FRONTEND_SRC.rglob("*.tsx")]
    )


def _documents_route_paths() -> list[str]:
    return [route.path for route in documents_router.router.routes if getattr(route, "path", None)]


def _report_key_targets(corpus: str) -> dict[str, set[str]]:
    """لكل مفتاح تقرير، مجموعة الامتدادات التي له زر حقيقي يصل إليها.

    مصدران فقط، كلاهما دليل وضع فعلي لا تخمين نصي: href حرفي مباشر
    (`.../boxes-balances.xlsx`) أو قيمة داخل إحدى كتلتي التصدير أعلاه.
    """
    targets: dict[str, set[str]] = defaultdict(set)
    for key, ext in re.findall(r"/([\w-]+)\.(pdf|xlsx)[\"'`]", corpus):
        targets[key].add(ext)
    for block_name, ext in _EXPORT_MAP_BLOCKS:
        m = re.search(rf"{block_name}[^{{]*\{{(.*?)\}}", corpus, re.S)
        if m:
            for key in re.findall(r":\s*'([\w-]+)'", m.group(1)):
                targets[key].add(ext)
    return targets


def test_every_document_route_is_reachable_from_a_button() -> None:
    corpus = _frontend_corpus()
    failures: list[str] = []

    single_id_routes = [p for p in _documents_route_paths() if "{report_key}" not in p]
    for path in single_id_routes:
        prefix = re.split(r"\{[^}]*\}", path, maxsplit=1)[0]
        if prefix not in corpus:
            failures.append(f"لا زر يصل بادئة المسار {prefix!r} (من {path!r}) في أي ملف واجهة")

    builders = documents_router._REPORT_BUILDERS
    excel_keys = documents_router._EXCEL_REPORT_KEYS
    assert builders, "لا تقارير مسجَّلة في _REPORT_BUILDERS — تحقّق من الاستيراد"
    targets = _report_key_targets(corpus)

    for key in builders:
        exts = targets.get(key, set())
        if "pdf" not in exts:
            failures.append(f"مفتاح التقرير {key!r} بلا زر PDF حقيقي يصل إليه في الواجهة")
        if key in excel_keys and "xlsx" not in exts:
            failures.append(f"مفتاح التقرير {key!r} مسجَّل بصيغة Excel لكن لا زر Excel يصل إليه في الواجهة")

    if failures:
        pytest.fail(
            f"{len(failures)} مسار مستند بلا زر يصل إليه:\n  " + "\n  ".join(failures)
        )
