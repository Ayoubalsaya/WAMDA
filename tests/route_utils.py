"""تعداد كل مسارات التطبيق بشكل مسطَّح. FastAPI الحديث (≥0.14x) يُدرج الموجّهات كسولاً في `_IncludedRouter` فلا يرى `app.routes`
المسارات الحقيقية مباشرة (كانت اختبارات تغطية المسارات تمرّ فارغةً بصمت) — هذا المُعدِّد يفرد السياقات الفعلية ويفشل إن بدا العدد ضئيلاً."""

from __future__ import annotations


MIN_ROUTES = 100


def all_routes(app) -> list:
    out: list = []

    def walk(routes):
        for r in routes:
            if hasattr(r, "effective_route_contexts"):
                walk(r.effective_route_contexts())
            elif getattr(r, "path", None) is not None:
                out.append(r)

    walk(app.routes)
    assert len(out) >= MIN_ROUTES, f"عدد المسارات المعدودة {len(out)} (الحد الأدنى {MIN_ROUTES}) — المُعدِّد لا يرى مسارات الموجّهات"
    return out
