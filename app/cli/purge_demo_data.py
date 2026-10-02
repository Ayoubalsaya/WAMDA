"""حذف بيانات العرض/الاختبار قبل إدخال أي بيانات حقيقية — تفاعلي، يطلب
تأكيداً صريحاً قبل أي حذف فعلي.

═══ السابقة الموحَّدة لأي بيانات اختبار يدوي/QA من الآن فصاعداً ═══
  · اسم مستخدم:   `qa_<شيء>`      مثال: qa_stage7
  · كود عميل:     `QA-<شيء>`      مثال: QA-STAGE7-001
  · كود شريك:     `QA-P-<شيء>`
  · كود حساب:     `QA-ACC-<شيء>` أو `QA-BANK-<شيء>`
هذه السابقة الوحيدة المطلوب تذكّرها لأي بيانات اختبار يدوي جديدة — أي
بيانات بها تُحذف بأمر واحد دائماً، بلا استثناء وبلا حاجة لتحديث هذا
الملف لاحقاً.

═══ أنماط قديمة مُغطاة رجعياً لأغراض التوافق (لا تُستخدَم لبيانات جديدة) ═══
  · `test_%`/`T-%`/`T-P-%`/`T-ACC-%`/`T-BANK-%` — اصطلاح `tests/factories.py`
    (اختبارات pytest المُلتزَمة فعلياً مثل test_concurrency.py/test_cli_admin.py)
  · `test-admin-%` — اصطلاح `tests/test_cli_admin.py`
  · `STG%` (أكواد عملاء) — بقايا اختبار يدوي من المرحلة ٦ قبل توحيد السابقة
  · `TEST%` (مستخدمون وعملاء) — شبكة أمان عامة لأي تسمية غير موحَّدة
  · `demo_admin` / `DEMO-%` — حساب/عميل العرض التأسيسي (§٩)

**النطاق حصراً** (لا يمسّ أي شيء آخر — لا currencies/locations/شجرة
الحسابات النظامية/client_currency_locations/founding_period):
  عملاء/شركاء/حسابات/مستخدمون مطابقون لما سبق + كل قيد يمسّ أياً منهم
  (كعميل/شريك/منشئ) + كل الجداول التابعة (أسطر القيد · دفعات الرمبي
  واستهلاكها · حركات السويفت · الأرصدة الافتتاحية ·
  مفاتيح التفرّد · الجلسات).

**قيد POSTED لا يُحذف عادة (§٥ قاعدة ٢: "لا حذف أبداً")** — مشغّل
`trg_journal_lines_no_edit_when_posted` يرفض ذلك بتصميمه. هذا الأمر
استثناء واعٍ ومحدود النطاق: يُعطَّل المشغّل داخل نفس معاملة الحذف
لبيانات العرض/الاختبار **فقط قبل دخول أي بيانات حقيقية**، ويُعاد تفعيله
فوراً بعدها — بلا استثناء لأي صف حقيقي مهما كان.

`audit_log` **لا يُمسّ إطلاقاً** (append-only، §٥ قاعدة ١١) — صفوفه التي
تشير إلى كيانات مُحذوفة تبقى أثراً تاريخياً صادقاً، و`entity_id` فيها
بلا قيد مفتاح أجنبي أصلاً فلا يتعارض حذفها مع بقاء تلك الصفوف.

**حارس بيئة إلزامي**: يرفض العمل كلياً إن كان `settings.app_env` غير
`local` — أداة حذف شامل بهذا الاتساع لا يجوز أن تُشغَّل عن طريق الخطأ
على أي بيئة نشر حقيقية، مهما كانت الثقة بالأنماط أعلاه.

**مستخدم تجريبي يشير إليه شيء حقيقي — لا يُحذف، يُعطَّل** (قرار مالك
صريح بعد حادثة `demo_admin` كـ`clients.created_by` لعميل حقيقي غير
تجريبي): بعد تطهير كل ما هو تجريبي فعلاً، أي مستخدم مطابق للأنماط أعلاه
لا يزال مرجعاً من صف حقيقي باقٍ (`journal_entries.created_by/posted_by`،
`clients.created_by`، اعتماد رصيد افتتاحي، إغلاق فترة، نافذة طوارئ، طلب
تعديل...) **لا يُحذف** — يُعطَّل (`is_active = false`) بدلاً من ذلك،
ويُطبَع تحذير صريح بالجدول والعمود وعيّنة من الصفوف التي منعت الحذف.
الحذف الجزئي الصامت (حذف المستخدم مع ترك مرجع يتيم) أسوأ من الرفض.
"""

from __future__ import annotations

import sys

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.engine import recompute


def _demo_client_codes(alias: str = "") -> str:
    col = f"{alias}.code" if alias else "code"
    return f"({col} LIKE 'DEMO-%' OR {col} LIKE 'QA-%' OR {col} LIKE 'T-%' OR {col} LIKE 'STG%' OR {col} LIKE 'TEST%')"


def _demo_partner_codes(alias: str = "") -> str:
    col = f"{alias}.code" if alias else "code"
    return f"({col} LIKE 'QA-P-%' OR {col} LIKE 'T-P-%')"


def _demo_account_codes(alias: str = "") -> str:
    col = f"{alias}.code" if alias else "code"
    return f"({col} LIKE 'QA-ACC-%' OR {col} LIKE 'QA-BANK-%' OR {col} LIKE 'T-ACC-%' OR {col} LIKE 'T-BANK-%')"


def _demo_usernames(alias: str = "") -> str:
    col = f"{alias}.username" if alias else "username"
    return (
        f"({col} = 'demo_admin' "
        rf"OR {col} LIKE 'qa\_%' ESCAPE '\' "
        rf"OR {col} LIKE 'test\_%' ESCAPE '\' "
        f"OR {col} LIKE 'test-admin-%' "
        f"OR {col} LIKE 'TEST%')"
    )


_DEMO_CLIENT_CODES = _demo_client_codes()
_DEMO_PARTNER_CODES = _demo_partner_codes()
_DEMO_ACCOUNT_CODES = _demo_account_codes()
_DEMO_USERNAMES = _demo_usernames()


def _counts(db: Session) -> dict[str, int]:
    rows = {
        "clients": db.execute(text(f"SELECT count(*) FROM clients WHERE {_DEMO_CLIENT_CODES}")).scalar(),
        "partners": db.execute(text(f"SELECT count(*) FROM partners WHERE {_DEMO_PARTNER_CODES}")).scalar(),
        "users": db.execute(text(f"SELECT count(*) FROM users WHERE {_DEMO_USERNAMES}")).scalar(),
        "journal_entries": db.execute(text(f"""
            SELECT count(*) FROM journal_entries e WHERE
                e.client_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})
                OR e.partner_id IN (SELECT id FROM partners WHERE {_DEMO_PARTNER_CODES})
                OR e.created_by IN (SELECT id FROM users WHERE {_DEMO_USERNAMES})
                OR e.id IN (
                    SELECT jl.entry_id FROM journal_lines jl JOIN accounts a ON a.id = jl.account_id
                    WHERE a.client_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})
                       OR a.partner_id IN (SELECT id FROM partners WHERE {_DEMO_PARTNER_CODES})
                       OR {_demo_account_codes("a")}
                )
        """)).scalar(),
    }
    return rows


def _demo_entry_ids_cte() -> str:
    """جزء SQL مشترك (subquery) لمعرّفات كل قيد يمسّ بيانات العرض/الاختبار."""
    return f"""(
        SELECT e.id FROM journal_entries e WHERE
            e.client_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})
            OR e.partner_id IN (SELECT id FROM partners WHERE {_DEMO_PARTNER_CODES})
            OR e.created_by IN (SELECT id FROM users WHERE {_DEMO_USERNAMES})
            OR e.id IN (
                SELECT jl.entry_id FROM journal_lines jl JOIN accounts a ON a.id = jl.account_id
                WHERE a.client_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})
                   OR a.partner_id IN (SELECT id FROM partners WHERE {_DEMO_PARTNER_CODES})
                   OR {_demo_account_codes("a")}
            )
    )"""


def _demo_account_ids_cte() -> str:
    return f"""(
        SELECT id FROM accounts WHERE
            client_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})
            OR partner_id IN (SELECT id FROM partners WHERE {_DEMO_PARTNER_CODES})
            OR {_DEMO_ACCOUNT_CODES}
    )"""


# جداول/أعمدة تشير إلى users.id — تُفحَص لكل مستخدم تجريبي قبل حذفه (انظر
# _purge_or_deactivate_demo_users). كل زوج (جدول، عمود المعرّف المعروض)
# يُستخدَم فقط لعرض تحذير مفهوم، لا لأي منطق حذف.
_USER_REFERENCE_CHECKS: list[tuple[str, str, str]] = [
    ("journal_entries", "created_by", "entry_no"),
    ("journal_entries", "posted_by", "entry_no"),
    ("clients", "created_by", "name_ar"),
    ("opening_balances", "approved_by", "id"),
    ("opening_reconciliation", "approved_by", "id"),
    ("periods", "closed_by", "year"),
    ("founding_period", "closed_by", "id"),
    ("outage_windows", "opened_by", "id"),
    ("outage_windows", "closed_by", "id"),
    ("edit_requests", "requested_by", "id"),
    ("edit_requests", "decided_by", "id"),
    ("entry_comments", "created_by", "id"),            # أُضيف ٢٠٢٦-١٠-٠٢ (جدول ١٤ب لم يُراجَع هنا)
    ("client_portal_invites", "created_by", "id"),     # أُضيف ٢٠٢٦-١٠-٠٢ (جدول دعوات البوابة)
]


def _purge_or_deactivate_demo_users(db: Session) -> dict[str, list[str]]:
    """لكل مستخدم تجريبي: يُحذف إن لم يبقَ أي مرجع حقيقي (غير تجريبي) إليه
    بعد التطهير أعلاه؛ وإلا **لا يُحذف** — يُعطَّل (`is_active=false`)
    ويُجمَع تحذير واضح بما منع الحذف (قرار مالك صريح: الحذف الجزئي الصامت
    أسوأ من الرفض)."""
    demo_users = db.execute(text(f"SELECT id, username FROM users WHERE {_DEMO_USERNAMES}")).all()
    blocked: dict[str, list[str]] = {}
    for user_id, username in demo_users:
        reasons: list[str] = []
        for table, column, label_col in _USER_REFERENCE_CHECKS:
            rows = db.execute(
                text(f"SELECT {label_col} FROM {table} WHERE {column} = :uid LIMIT 3"), {"uid": user_id}
            ).scalars().all()
            if rows:
                total = db.execute(text(f"SELECT count(*) FROM {table} WHERE {column} = :uid"), {"uid": user_id}).scalar()
                sample = "، ".join(str(r) for r in rows)
                reasons.append(f"{table}.{column} ({total}): {sample}" + (" ..." if total > len(rows) else ""))
        if reasons:
            db.execute(text("UPDATE users SET is_active = false WHERE id = :uid"), {"uid": user_id})
            blocked[username] = reasons
        else:
            db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    return blocked


# كل جدول يحمل مفتاحاً أجنبياً إلى أحد هذه الجداول يجب أن يُعالَج صراحةً في `_purge` (حذف/تفريغ)
# أو في `_USER_REFERENCE_CHECKS` (مستخدمون)، وإلا فشل الحذف بقيد FK متأخراً — حادثة حقيقية:
# `client_portal_invites` أُضيف ٢٠٢٦-١٠-٠٢ ولم تُحدَّث الأداة. `tests/test_cli_purge_demo_data.py`
# يقارن هذه القائمة بمخطط القاعدة الفعلي ويفشل إن أُضيف جدول جديد بلا مراجعة هنا.
PURGE_COVERED_FOREIGN_KEYS: set[tuple[str, str]] = {
    # → accounts
    ("account_balances", "account_id"), ("account_number_assignments", "parent_id"), ("account_number_counters", "parent_id"),
    ("accounts", "parent_id"), ("currency_lots", "account_id"), ("journal_lines", "account_id"),
    ("opening_balances", "contra_account_id"), ("opening_balances", "account_id"), ("opening_reconciliation", "account_id"),
    # → clients
    ("accounts", "client_id"), ("client_credit_limits", "client_id"), ("client_portal_invites", "client_id"),
    ("journal_entries", "client_id"),
    # → journal_entries / currency_lots
    ("lot_consumptions", "lot_id"), ("currency_lots", "source_entry_id"), ("edit_requests", "entry_id"),
    ("entry_comments", "entry_id"), ("idempotency_keys", "entry_id"), ("journal_entries", "reversed_by_entry_id"),
    ("journal_entries", "reverses_entry_id"), ("journal_entries", "replaces_entry_id"), ("journal_lines", "entry_id"),
    ("lot_consumptions", "entry_id"), ("opening_reconciliation", "resolving_entry_id"),
    ("partner_statement_lines", "matched_entry_id"), ("swift_movements", "return_entry_id"),
    ("swift_movements", "in_entry_id"), ("swift_movements", "out_entry_id"),
    # → partners
    ("accounts", "partner_id"), ("journal_entries", "partner_id"), ("partner_statements", "partner_id"),
    # → users (تُعالَج عبر _USER_REFERENCE_CHECKS: حذف المستخدم أو تعطيله)
    ("client_portal_invites", "created_by"), ("clients", "created_by"), ("edit_requests", "decided_by"),
    ("edit_requests", "requested_by"), ("entry_comments", "created_by"), ("founding_period", "closed_by"),
    ("journal_entries", "posted_by"), ("journal_entries", "created_by"), ("opening_balances", "approved_by"),
    ("opening_reconciliation", "approved_by"), ("outage_windows", "opened_by"), ("outage_windows", "closed_by"),
    ("periods", "closed_by"),
    ("user_backup_codes", "user_id"),  # تُحذف مع المستخدم التجريبي (٢٠٢٦-١٠-٠٣)
}
PURGE_FK_TARGET_TABLES = ("accounts", "clients", "journal_entries", "currency_lots", "partners", "swift_movements", "users")


def _purge(db: Session) -> dict[str, list[str]]:
    entries = _demo_entry_ids_cte()
    accounts = _demo_account_ids_cte()

    # ١) فكّ أي إشارة عكس/معكوسية/استبدال قبل الحذف (ذاتية الإشارة على
    # journal_entries — إضافة replaces_entry_id هنا إلزامية مع كل عمود
    # ذاتي الإشارة جديد، وإلا فشل الحذف بانتهاك مفتاح أجنبي بصمت لاحقاً)
    db.execute(text(f"UPDATE journal_entries SET reversed_by_entry_id = NULL WHERE reversed_by_entry_id IN {entries}"))
    db.execute(text(f"UPDATE journal_entries SET reverses_entry_id = NULL WHERE reverses_entry_id IN {entries}"))
    db.execute(text(f"UPDATE journal_entries SET replaces_entry_id = NULL WHERE replaces_entry_id IN {entries}"))

    # ٢) الجداول التابعة للقيود
    db.execute(text(f"DELETE FROM entry_comments WHERE entry_id IN {entries}"))
    db.execute(text(f"DELETE FROM edit_requests WHERE entry_id IN {entries}"))
    db.execute(text(f"UPDATE partner_statement_lines SET matched_entry_id = NULL WHERE matched_entry_id IN {entries}"))
    # **إعادة كمية الدفعة قبل حذف استهلاكها** (٢٠٢٦-١٠-٠٢): بيع تجريبي (عميل `QA-`/`T-`…) قد يكون
    # استهلك من دفعة رمبي «حقيقية» لا تُحذَف (مصدرها سويفت وصول حقيقي). حذف صفوف الاستهلاك بلا
    # إعادة `remaining_qty` كان يُخرج الكمية من المخزون للأبد: `LOT-2026-0108` نقصت ١٣٦ بلا أي
    # سجل استهلاك يفسّر ذلك، وفشل `recompute.verify` بعدها. الدفعات التي ستُحذف نفسها لا تحتاج إعادة.
    db.execute(text(f"""
        UPDATE currency_lots l SET remaining_qty = l.remaining_qty + c.qty
        FROM (SELECT lot_id, SUM(CASE WHEN reverses_consumption_id IS NULL THEN qty ELSE -qty END) AS qty
              FROM lot_consumptions WHERE entry_id IN {entries} GROUP BY lot_id) c
        WHERE l.id = c.lot_id AND l.source_entry_id NOT IN {entries}
    """))
    db.execute(text("UPDATE currency_lots SET status = 'OPEN', closed_at = NULL WHERE status = 'CLOSED' AND remaining_qty > 0"))
    db.execute(text(f"DELETE FROM lot_consumptions WHERE entry_id IN {entries}"))
    db.execute(text(f"DELETE FROM idempotency_keys WHERE entry_id IN {entries}"))
    db.execute(text(f"""
        DELETE FROM lot_consumptions WHERE lot_id IN (SELECT id FROM currency_lots WHERE source_entry_id IN {entries})
    """))
    db.execute(text(f"DELETE FROM currency_lots WHERE source_entry_id IN {entries}"))
    db.execute(text(f"DELETE FROM lot_consumptions WHERE lot_id IN (SELECT id FROM currency_lots WHERE account_id IN {accounts})"))
    db.execute(text(f"DELETE FROM currency_lots WHERE account_id IN {accounts}"))
    db.execute(text(f"""
        DELETE FROM swift_movements
        WHERE out_entry_id IN {entries} OR in_entry_id IN {entries} OR return_entry_id IN {entries}
    """))
    db.execute(text(f"""
        UPDATE opening_reconciliation SET resolving_entry_id = NULL WHERE resolving_entry_id IN {entries}
    """))
    db.execute(text(f"DELETE FROM opening_balances WHERE account_id IN {accounts} OR contra_account_id IN {accounts}"))
    db.execute(text(f"DELETE FROM opening_reconciliation WHERE account_id IN {accounts}"))

    # ٣) أسطر القيد — تعطيل مؤقت لمشغّل عدم التعديل بعد الترحيل، نطاق هذه
    # المعاملة فقط، لبيانات العرض/الاختبار حصراً (انظر docstring أعلى الملف)
    db.execute(text("ALTER TABLE journal_lines DISABLE TRIGGER trg_journal_lines_no_edit_when_posted"))
    try:
        db.execute(text(f"DELETE FROM journal_lines WHERE entry_id IN {entries}"))
        db.execute(text(f"DELETE FROM journal_entries WHERE id IN {entries}"))
    finally:
        db.execute(text("ALTER TABLE journal_lines ENABLE TRIGGER trg_journal_lines_no_edit_when_posted"))

    # ٤) أرصدة/بيانات الحسابات التجريبية، ثم الحسابات نفسها
    db.execute(text(f"DELETE FROM account_balances WHERE account_id IN {accounts}"))
    db.execute(text(f"DELETE FROM client_credit_limits WHERE client_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})"))
    # دعوات بوابة العميل (جدول أُضيف ٢٠٢٦-١٠-٠٢) — بلا هذا يفشل حذف أي عميل `QA-`/`T-` بقيد FK
    db.execute(text(f"DELETE FROM client_portal_invites WHERE client_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})"))
    # جلسات بوابة العميل (sessions.subject_id بلا FK صلب — تعدد أشكال، كجلسات المستخدمين)
    db.execute(text(f"""
        DELETE FROM sessions WHERE subject_type = 'CLIENT' AND subject_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})
    """))
    db.execute(text(f"DELETE FROM accounts WHERE id IN {accounts}"))

    # ٥) العملاء والشركاء أنفسهم
    db.execute(text(f"DELETE FROM clients WHERE {_DEMO_CLIENT_CODES}"))
    # كشوف مراسلين لشريك تجريبي (جدولا المطابقة، المرحلة ١٣) قبل حذف الشريك
    db.execute(text(f"""
        DELETE FROM partner_statement_lines WHERE statement_id IN
            (SELECT id FROM partner_statements WHERE partner_id IN (SELECT id FROM partners WHERE {_DEMO_PARTNER_CODES}))
    """))
    db.execute(text(f"DELETE FROM partner_statements WHERE partner_id IN (SELECT id FROM partners WHERE {_DEMO_PARTNER_CODES})"))
    db.execute(text(f"DELETE FROM partners WHERE {_DEMO_PARTNER_CODES}"))

    # ٦) جلسات ثم المستخدمون التجريبيون (sessions.subject_id بلا FK صلب — تعدد أشكال)
    db.execute(text(f"""
        DELETE FROM sessions WHERE subject_type = 'USER' AND subject_id IN (SELECT id FROM users WHERE {_DEMO_USERNAMES})
    """))
    db.execute(text(f"DELETE FROM user_backup_codes WHERE user_id IN (SELECT id FROM users WHERE {_DEMO_USERNAMES})"))
    blocked = _purge_or_deactivate_demo_users(db)

    # ٧) إعادة بناء account_balances بالكامل — إلزامي، لا اختياري: قيود
    # العرض/الاختبار المحذوفة قد تكون مسّت حسابات **مشتركة حقيقية** (١١٠١
    # مثلاً) لا تخصّها وحدها، فحذف أسطرها بلا إعادة بناء الرصيد المشتق
    # يترك account_balances.balance لتلك الحسابات المشتركة فاسداً بصمت.
    db.flush()
    recompute.rebuild(db)
    return blocked


def run() -> None:
    if settings.app_env != "local":
        print(
            f"مرفوض — APP_ENV=\"{settings.app_env}\" وليس \"local\". "
            "هذا الأمر لا يعمل إلا في بيئة تطوير محلية — لا يُشغَّل على أي بيئة نشر أبداً."
        )
        sys.exit(1)

    db = SessionLocal()
    try:
        counts = _counts(db)
        print("=== حذف بيانات العرض/الاختبار — معاينة قبل أي حذف فعلي ===")
        print(f"  عملاء تجريبيون:      {counts['clients']}")
        print(f"  شركاء تجريبيون:      {counts['partners']}")
        print(f"  مستخدمون تجريبيون:   {counts['users']}")
        print(f"  قيود مرتبطة بهم:     {counts['journal_entries']}")

        if sum(counts.values()) == 0:
            print("\nلا بيانات عرض/اختبار مطابقة — لا شيء ليُحذف.")
            db.rollback()
            return

        print(
            "\nهذا حذف فعلي بلا رجعة — بما في ذلك قيود مُرحّلة (استثناء واعٍ "
            "لبيانات العرض/الاختبار فقط، انظر رأس الملف). لا يمسّ العملات "
            "أو المواقع أو شجرة الحسابات أو audit_log."
        )
        confirmation = input("اكتب DELETE (بالإنجليزية) للتأكيد: ").strip()
        if confirmation != "DELETE":
            print("أُلغي — لم يُحذف شيء.")
            db.rollback()
            return

        blocked = _purge(db)
        db.commit()
        print("\nتم الحذف بنجاح.")
        if blocked:
            print(
                "\nتحذير: المستخدمون التاليون لم يُحذفوا لأن بيانات حقيقية "
                "(غير تجريبية) لا تزال تشير إليهم — عُطِّلوا (is_active=false) بدلاً "
                "من الحذف الجزئي الصامت:"
            )
            for username, reasons in blocked.items():
                print(f"\n  · {username}:")
                for reason in reasons:
                    print(f"      - {reason}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
