"""مصفوفة الصلاحيات الكاملة — §٧-١٣ حرفياً.

| الإجراء | مدير | محاسب | عميل |
|---|:--:|:--:|:--:|
| إدخال وترحيل | ✔ | ✔ | ✗ |
| تعديل قيد مُرحّل | ✔ | ✗ (يطلب) | ✗ |
| قيد بأثر رجعي / طوارئ | ✔ | ✗ | ✗ |
| فتح فترة مقفلة | ✔ | ✗ | ✗ |
| تجاوز ائتمان أو رصيد سالب | ✔ | ✗ | ✗ |
| المطابقة والأرصدة الافتتاحية | ✔ | ✗ | ✗ |
| كشف حسابه هو | — | — | ✔ + PDF |

"محاسب يطلب" لتعديل قيد مُرحّل يعني `edit_requests` (§٥ قاعدة ٣) — ليس
صلاحية تنفيذ مباشرة، فهو مرفوض هنا عمداً؛ رفع الطلب نفسه إجراء منفصل
غير مذكور في هذا الجدول (لا يحتاج صلاحية "مدير" لتقديمه).
"""

from __future__ import annotations

import enum


class Action(str, enum.Enum):
    POST_ENTRY = "POST_ENTRY"
    EDIT_POSTED_ENTRY = "EDIT_POSTED_ENTRY"
    BACKDATED_OR_OUTAGE_ENTRY = "BACKDATED_OR_OUTAGE_ENTRY"
    REOPEN_CLOSED_PERIOD = "REOPEN_CLOSED_PERIOD"
    OVERRIDE_CREDIT_OR_BALANCE = "OVERRIDE_CREDIT_OR_BALANCE"
    RECONCILIATION = "RECONCILIATION"
    OPENING_BALANCES = "OPENING_BALANCES"
    VIEW_OWN_STATEMENT = "VIEW_OWN_STATEMENT"


ADMIN = "ADMIN"
ACCOUNTANT = "ACCOUNTANT"
CLIENT_ROLE = "CLIENT"  # ليس صفاً في users.role (§٥ قاعدة ٦ CHECK) — دور منطقي لحامل جلسة عميل فقط

PERMISSION_MATRIX: dict[Action, frozenset[str]] = {
    Action.POST_ENTRY: frozenset({ADMIN, ACCOUNTANT}),
    Action.EDIT_POSTED_ENTRY: frozenset({ADMIN}),
    Action.BACKDATED_OR_OUTAGE_ENTRY: frozenset({ADMIN}),
    Action.REOPEN_CLOSED_PERIOD: frozenset({ADMIN}),
    Action.OVERRIDE_CREDIT_OR_BALANCE: frozenset({ADMIN}),
    Action.RECONCILIATION: frozenset({ADMIN}),
    Action.OPENING_BALANCES: frozenset({ADMIN}),
    Action.VIEW_OWN_STATEMENT: frozenset({CLIENT_ROLE}),
}


class PermissionDeniedError(Exception):
    def __init__(self, role: str, action: Action):
        self.role = role
        self.action = action
        super().__init__(f"الدور {role} لا يملك صلاحية {action.value}")


def has_permission(role: str, action: Action) -> bool:
    return role in PERMISSION_MATRIX.get(action, frozenset())


def require_permission(role: str, action: Action) -> None:
    if not has_permission(role, action):
        raise PermissionDeniedError(role, action)
