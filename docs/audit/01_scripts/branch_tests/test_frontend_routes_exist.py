"""حارس دائم: كل مسار API تستدعيه الواجهة موجود فعلاً في مخطط الخادم.

لماذا هذا الاختبار موجود:
    بقية الاختبارات تستدعي الخادم مباشرةً (TestClient/الدوال)، فلا ترى
    عنوان URL الذي يكتبه المتصفح. خطأ مطبعي أو مسار محذوف في
    `frontend/src/**` يمرّ من كل الاختبارات الخضراء ثم يفشل عند أول
    نقرة حقيقية بـ ٤٠٤. هذا الاختبار يسدّ تلك الفجوة تحديداً.

كيف يطابق:
    يُقارَن المسار مقطعاً بمقطع. المقطع الديناميكي في الواجهة
    (`${clientId}`) يطابق أي مقطع في المخطط — سواء كان وسيطاً
    (`{client_id}`) أو قيمة حرفية (`close` من اتحاد 'close' | 'reopen').
    هذا يتجنّب الإنذارات الكاذبة مع الإبقاء على كشف المسار غير الموجود
    أصلاً، وهو الخطأ الذي نريد منعه.
"""

from __future__ import annotations

import io
import pathlib
import re

import pytest

from app.main import app

_FRONTEND_SRC = pathlib.Path(r"C:/Users/HP/Desktop/wamda 3.0V/wamda/frontend/src")
_CALL_START = re.compile(r"\bapi\.(get|post|patch|put)\s*(?:<.*?>)?\s*\(\s*", re.S)
_CLOSERS = {"`": "`", "'": "'", '"': '"'}


def _read_first_argument(src: str, i: int) -> str | None:
    """يقرأ الوسيط النصي الأول مع احترام القوالب المتداخلة (`${ ... `x` ... }`)."""
    if i >= len(src) or src[i] not in _CLOSERS:
        return None  # مسار مبني في متغيّر خارجي — يُتجاوز، انظر التقرير أدناه
    quote = src[i]
    out: list[str] = []
    depth = 0
    i += 1
    while i < len(src):
        ch = src[i]
        if ch == "\\":
            i += 2
            continue
        if quote == "`" and ch == "$" and src[i : i + 2] == "${":
            if depth == 0:
                out.append("${")  # العلامة تُكتب مرة واحدة للتداخل الخارجي فقط
            depth += 1
            i += 2
            continue
        if depth:
            # داخل ${...}: نتتبّع الأقواس فقط حتى نغلق التعبير
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out.append("}")
                    i += 1
                    continue
            i += 1
            continue
        if ch == quote:
            return "".join(out)
        out.append(ch)
        i += 1
    return None


def _normalise(path: str) -> str:
    path = re.sub(r"\$\{[^}]*\}", "{}", path)  # مقطع ديناميكي
    path = path.split("?", 1)[0]
    return path.rstrip("/") or "/"


def _candidates(path: str) -> list[str]:
    """صيغ مقبولة للمسار الواحد.

    الجزء الديناميكي الملتصق بنهاية مقطع حرفي (`/clients${...}`) قد يكون
    سلسلة استعلام (`?q=`) لا مقطعاً جديداً، فنقبل الصيغتين: بوجوده وبحذفه.
    """
    norm = _normalise(path)
    out = [norm]
    if norm.endswith("{}") and not norm.endswith("/{}"):
        out.append(norm[: -len("{}")].rstrip("/") or "/")
    return out


def _collect_calls() -> list[tuple[str, int, str, str]]:
    calls: list[tuple[str, int, str, str]] = []
    for file in sorted([*_FRONTEND_SRC.rglob("*.ts"), *_FRONTEND_SRC.rglob("*.tsx")]):
        src = io.open(file, encoding="utf-8").read()
        for m in _CALL_START.finditer(src):
            raw = _read_first_argument(src, m.end())
            if raw is None or not raw.startswith("/"):
                continue
            line = src[: m.start()].count("\n") + 1
            calls.append((file.as_posix(), line, m.group(1).lower(), raw))
    return calls


def _schema_paths() -> dict[str, set[str]]:
    spec = app.openapi()
    return {p: {m.lower() for m in ops} for p, ops in spec["paths"].items()}


def _segment_regex(schema_segment: str) -> re.Pattern[str]:
    """`{report_key}.xlsx` → تعبير يطابق `boxes-balances.xlsx`.

    الوسيط قد يكون جزءاً من المقطع لا المقطع كله، فالمطابقة على مستوى
    المقطع وحده لا تكفي.
    """
    out = "".join(
        "[^/]+" if part.startswith("{") and part.endswith("}") else re.escape(part)
        for part in re.split(r"(\{[^}]*\})", schema_segment)
        if part
    )
    return re.compile(f"^{out}$")


def _matches(frontend: str, schema: str) -> bool:
    f_parts, s_parts = frontend.split("/"), schema.split("/")
    if len(f_parts) != len(s_parts):
        return False
    for f, s in zip(f_parts, s_parts):
        if f == "{}":
            continue  # مقطع ديناميكي كامل — قد يكون وسيطاً أو قيمة اتحاد حرفية
        # الجزء الديناميكي داخل المقطع يُمثَّل بنص نائب ثم يُختبر على النمط
        if not _segment_regex(s).match(f.replace("{}", "X")):
            return False
    return True


def test_every_frontend_api_path_exists_in_schema() -> None:
    calls = _collect_calls()
    assert calls, "لم يُعثر على أي استدعاء api.* — تحقّق من مسار frontend/src"

    schema = _schema_paths()
    failures: list[str] = []
    for file, line, method, raw in calls:
        hits = [p for p in schema for c in _candidates(raw) if _matches(c, p)]
        if not hits:
            failures.append(f"{file}:{line} — {method.upper()} {raw!r}: لا مسار مطابق في المخطط")
        elif not any(method in schema[p] for p in hits):
            allowed = sorted({m for p in hits for m in schema[p]})
            failures.append(
                f"{file}:{line} — {raw!r} موجود لكن بلا {method.upper()} (المتاح: {allowed})"
            )

    if failures:
        pytest.fail(
            f"{len(failures)} استدعاء في الواجهة لا يطابق مخطط الخادم:\n  " + "\n  ".join(failures)
        )


# جذور المسارات التي يخدمها الخادم — تُشتق من المخطط نفسه فلا تتقادم يدوياً.
def _api_roots() -> set[str]:
    return {p.split("/")[1] for p in _schema_paths() if len(p.split("/")) > 1 and p != "/"}


def test_api_shaped_string_literals_exist_in_schema() -> None:
    """يغطي المسارات التي تصل `api.*` عبر متغيّر أو خاصية JSX.

    `ActivityTab endpoint="/reports/activity-by-month"` لا يظهر في الاختبار
    الأول لأن الوسيط متغيّر عند نقطة الاستدعاء — هذا الفحص يمسك أي نص
    يبدأ بجذر مسار معروف أينما كُتب في الواجهة.
    """
    roots = _api_roots()
    literal = re.compile(r"[`'\"](/[A-Za-z0-9_\-./{}$]*)[`'\"]")
    schema = _schema_paths()

    failures: list[str] = []
    for file in sorted([*_FRONTEND_SRC.rglob("*.ts"), *_FRONTEND_SRC.rglob("*.tsx")]):
        src = io.open(file, encoding="utf-8").read()
        for m in literal.finditer(src):
            raw = m.group(1)
            parts = raw.split("/")
            if len(parts) < 2 or parts[1] not in roots:
                continue  # ليس مساراً للخادم (مسار توجيه داخلي، أصل ثابت، ...)
            if not any(_matches(c, p) for p in schema for c in _candidates(raw)):
                line = src[: m.start()].count("\n") + 1
                failures.append(f"{file.as_posix()}:{line} — {raw!r} لا يطابق أي مسار في المخطط")

    if failures:
        pytest.fail(
            f"{len(failures)} نص يشبه مسار API لا يوجد في المخطط:\n  " + "\n  ".join(failures)
        )
