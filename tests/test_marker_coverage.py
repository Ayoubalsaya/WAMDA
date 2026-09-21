"""يتحقق أن كل اختبار قبول ١–٥٠ (§١١ من الوثيقة الوظيفية) عليه علامة
`@pytest.mark.acceptance(n)` واحدة على الأقل — بلا هذا الفحص، تقرير
التغطية النهائي مجرد ادعاء لا شيء يتحقق منه.

**يعمل فقط عند تشغيل المجموعة كاملة** (`pytest` بلا مسار مُحدَّد، أو مع
كل ملفات `test_acceptance_*.py` معاً) — تشغيل ملف واحد فقط يجعل بقية
الأرقام "مفقودة" حتماً، وهذا متوقع لا خطأ.
"""

from __future__ import annotations

from tests.conftest import ACCEPTANCE_CANCELLED, ACCEPTANCE_VERIFIED_VIA_PLAYWRIGHT, TOTAL_ACCEPTANCE_TESTS


def test_all_fifty_acceptance_numbers_covered(request):
    coverage: dict[int, list[str]] = getattr(request.config, "_acceptance_coverage", {})
    covered_or_excused = set(coverage) | set(ACCEPTANCE_VERIFIED_VIA_PLAYWRIGHT) | set(ACCEPTANCE_CANCELLED)
    missing = sorted(set(range(1, TOTAL_ACCEPTANCE_TESTS + 1)) - covered_or_excused)
    duplicated = {n: ids for n, ids in coverage.items() if len(ids) > 1}

    print("\n=== تقرير تغطية اختبارات القبول (§١١) ===")
    for n in range(1, TOTAL_ACCEPTANCE_TESTS + 1):
        ids = coverage.get(n, [])
        if ids:
            status = "OK"
        elif n in ACCEPTANCE_VERIFIED_VIA_PLAYWRIGHT:
            status = "PLAYWRIGHT"
        elif n in ACCEPTANCE_CANCELLED:
            status = "CANCELLED"
        else:
            status = "MISSING"
        detail = ", ".join(ids) or ACCEPTANCE_VERIFIED_VIA_PLAYWRIGHT.get(n, "") or ACCEPTANCE_CANCELLED.get(n, "")
        print(f"  {n:>2}: {status:<10} {detail}")

    if duplicated:
        print("\n-- أرقام بأكثر من اختبار (قد يكون مقصوداً) --")
        for n, ids in sorted(duplicated.items()):
            print(f"  {n}: {ids}")

    assert not missing, f"اختبارات قبول غير مغطاة إطلاقاً بأي علامة acceptance: {missing}"
