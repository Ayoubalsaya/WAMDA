"""كل مسار كتابة له سطر تدقيق — أو هو ترحيل دفتري يحمل قيده سجله بنفسه (٢٠٢٦-١٠-٠٦، تدقيق U-05).

قاعدة §٥-١١: كل كتابة تُسجَّل. الاستثناء الوحيد المعلَن: مسارات الترحيل الدفتري (`LEDGER_POSTING`) — القيد نفسه يحمل من أنشأه
ومتى ولماذا (`created_by`/`posted_by`/`created_at`/`posted_at`/الوصف/سبب الأثر الرجعي/سبب التجاوز)، فلا يُكرَّر في `audit_log`
(إلا التجاوز بسبب فيه سطره من المحرك). الفحص بنيوي (تحليل AST لما يستدعيه المعالج بعمق محدود) فيفشل إن أُضيف مسار كتابة جديد
بلا `log_write` ولم يُصرَّح به هنا."""

from __future__ import annotations

import ast
import importlib
import inspect
import textwrap

from app.main import app

WRITE = {"POST", "PUT", "PATCH", "DELETE"}

# ترحيل دفتري: السجل هو القيد نفسه (انظر test_ledger_entries_carry_who_when_why)
LEDGER_POSTING = {
    "POST /operations/receipt", "POST /operations/payment", "POST /operations/exchange", "POST /operations/exchange/from-lot",
    "POST /operations/exchange-chain", "POST /operations/expense", "POST /operations/local-move", "POST /operations/remit-out",
    "POST /operations/adjustment", "POST /operations/cash-transfer", "POST /operations/opening", "POST /operations/swift-in",
    "POST /operations/swift-out", "POST /operations/swift-return",
}

# مسارات لا تكتب بيانات أعمال (قراءة بصيغة POST، أو توليد مستند/ملف بلا تغيير حالة، أو مصادقة تدقّقها خدماتها)
NO_BUSINESS_WRITE: set[str] = {
    "POST /portal/invite/verify",  # يتحقق من صلاحية رمز الدعوة ويُرجع الاسم الأول فقط — لا يغيّر حالة (القبول `invite/accept` مدقَّق)
}


def _write_routes():
    for r in app.routes:
        methods = getattr(r, "methods", None) or set()
        for m in sorted(methods & WRITE):
            yield f"{m} {r.path}", r.endpoint


def _calls_log_write(fn, seen: set, depth: int = 0) -> bool:
    if fn in seen or depth > 3:
        return False
    seen.add(fn)
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError):
        return False
    mod = inspect.getmodule(fn)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name == "log_write":
            return True
        target = None
        if isinstance(f, ast.Name):
            target = getattr(mod, f.id, None)
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            holder = getattr(mod, f.value.id, None)
            if inspect.ismodule(holder):
                target = getattr(holder, f.attr, None)
        if inspect.isfunction(target) and (inspect.getmodule(target) or mod).__name__.startswith("app.") and _calls_log_write(target, seen, depth + 1):
            return True
    return False


def test_every_write_route_has_an_audit_line_or_is_declared_ledger():
    missing = [route for route, fn in _write_routes()
               if route not in LEDGER_POSTING and route not in NO_BUSINESS_WRITE and not _calls_log_write(fn, set())]
    assert not missing, "مسارات كتابة بلا سطر تدقيق (أضف audit.log_write أو صرّح بها هنا مع السبب):\n" + "\n".join(missing)


def test_ledger_routes_declared_here_really_exist_and_do_not_duplicate_the_audit():
    routes = dict(_write_routes())
    assert LEDGER_POSTING <= set(routes), sorted(LEDGER_POSTING - set(routes))
    for route in LEDGER_POSTING:
        assert not _calls_log_write(routes[route], set()), f"{route} يكرّر في audit_log ما يحمله القيد نفسه"
