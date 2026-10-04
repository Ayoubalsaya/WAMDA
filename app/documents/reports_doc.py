"""مستندات التقارير الداخلية (§٨) — كلها للموظف لا للعميل (لا قيد على
cost_rate هنا، بخلاف `receipt.py`). كل دالة تُعيد سياق `report_table.html`
الجاهز — نفس القالب لكل التقارير، البيانات مُعاد استخدامها من دوال
المرحلة ٩/٨ (`app/routers/reports.py`/`dashboard.py`) مباشرة بلا HTTP،
لا إعادة اشتقاق منطق محاسبي هنا.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session as OrmSession

from app.documents.common import base_context
from app.documents.formatting import currency_decimals_map, format_amount, format_rate

_OP_LABELS_AR: dict[str, str] = {
    "RECEIPT": "قبض", "PAYMENT": "صرف", "EXCHANGE": "صرافة", "CASH_TRANSFER": "تحويل بعمولة",
    "LOCAL_MOVE": "نقل داخلي", "REMIT_OUT": "إرسال خارجي", "SWIFT_OUT": "سويفت خروج", "SWIFT_IN": "سويفت وصول",
    "SWIFT_RETURN": "سويفت مرتجع", "EXPENSE": "مصروف", "OPENING": "رصيد افتتاحي", "ADJUSTMENT": "تسوية",
}


def _amounts_summary_item(label: str, pairs, decimals_map: dict[str, int]) -> dict:
    return {
        "label": label,
        "lines": [{"k": p.currency_code, "v": format_amount(p.amount, p.currency_code, decimals_map)} for p in pairs],
    }


def build_trial_balance_context(db: OrmSession, *, doc_size: str, now: datetime, work_timezone: str) -> dict:
    from app.routers.reports import trial_balance

    body = trial_balance(db)
    dec = currency_decimals_map(db)
    ctx = base_context(db, now=now, work_timezone=work_timezone)
    ctx.update({
        "doc_size": doc_size, "doc_title": "ميزان المراجعة",
        "doc_subtitle": "متوازن" if body.balanced else "غير متوازن — يستحق فحصاً",
        "qr_data_uri": None,
        "columns": ["الكود", "الحساب", "النوع", "العملة", "مدين", "دائن"],
        "rows": [
            [r.account_code, r.account_name_ar, r.account_type, r.currency_code or "—",
             format_amount(r.debit, r.currency_code, dec) if r.debit else "—",
             format_amount(r.credit, r.currency_code, dec) if r.credit else "—"]
            for r in body.rows
        ],
        "summary": [
            _amounts_summary_item("إجمالي مدين", body.total_debit_by_currency, dec),
            _amounts_summary_item("إجمالي دائن", body.total_credit_by_currency, dec),
        ],
    })
    return ctx


def build_founding_reconciliation_context(db: OrmSession, *, doc_size: str, now: datetime, work_timezone: str) -> dict:
    from app.routers.reports import founding_reconciliation

    body = founding_reconciliation(db)
    dec = currency_decimals_map(db)
    ctx = base_context(db, now=now, work_timezone=work_timezone)
    ctx.update({
        "doc_size": doc_size, "doc_title": "المصالحة التأسيسية", "doc_subtitle": None, "qr_data_uri": None,
        "columns": ["البند", "القيمة"],
        "rows": [
            ["عدد الأرصدة الافتتاحية", str(body.opening_balances_count)],
            ["بنود مصالحة مفتوحة", str(body.open_reconciliation_items)],
        ],
        "summary": [
            _amounts_summary_item("رصيد فروق التأسيس (٣٩٠٠)", body.suspense_balance_by_currency, dec),
            _amounts_summary_item("إجمالي الأرصدة الافتتاحية", body.opening_balances_total_by_currency, dec),
        ],
    })
    return ctx


def build_balance_overrides_context(db: OrmSession, *, doc_size: str, now: datetime, work_timezone: str) -> dict:
    from app.routers.reports import balance_overrides

    rows = balance_overrides(db)
    labels = {"CREDIT_LIMIT_OVERRIDE": "تجاوز حد ائتمان", "NEGATIVE_BALANCE_OVERRIDE": "تجاوز رصيد سالب"}
    ctx = base_context(db, now=now, work_timezone=work_timezone)
    ctx.update({
        "doc_size": doc_size, "doc_title": "تجاوزات الرصيد", "doc_subtitle": None, "qr_data_uri": None,
        "columns": ["التاريخ", "النوع", "الحساب", "رقم القيد", "السبب", "بواسطة"],
        "rows": [
            [r.created_at.strftime("%Y-%m-%d %H:%M"), labels.get(r.action, r.action), r.account_code or "—",
             r.entry_no or "—", r.reason or "—", r.actor_username or "—"]
            for r in rows
        ],
        "summary": None,
    })
    return ctx


def build_emergency_entries_context(db: OrmSession, *, doc_size: str, now: datetime, work_timezone: str) -> dict:
    from app.routers.reports import emergency_entries

    rows = emergency_entries(db)
    ctx = base_context(db, now=now, work_timezone=work_timezone)
    ctx.update({
        "doc_size": doc_size, "doc_title": "قيود الطوارئ", "doc_subtitle": None, "qr_data_uri": None,
        "columns": ["رقم القيد", "تاريخ القيد", "النوع", "وقت العملية الفعلي", "سبب التأخير"],
        "rows": [
            [r.entry_no, r.entry_date.isoformat(), _OP_LABELS_AR.get(r.operation_type, r.operation_type),
             r.real_operation_time.strftime("%Y-%m-%d %H:%M") if r.real_operation_time else "—", r.backdate_reason or "—"]
            for r in rows
        ],
        "summary": None,
    })
    return ctx


def build_monthly_profit_context(db: OrmSession, *, doc_size: str, now: datetime, work_timezone: str) -> dict:
    from app.routers.reports import profit_by_period

    rows = profit_by_period(granularity="monthly", date_from=None, date_to=None, db=db)
    dec = currency_decimals_map(db)

    def fmt_list(pairs):
        return "، ".join(f"{format_amount(p.amount, p.currency_code, dec)} {p.currency_code}" for p in pairs) or "—"

    ctx = base_context(db, now=now, work_timezone=work_timezone)
    ctx.update({
        "doc_size": doc_size, "doc_title": "الأرباح الشهرية", "doc_subtitle": None, "qr_data_uri": None,
        "columns": ["الشهر", "فرق التحويل", "فروق الصرف", "عمولة الصرافة", "الصافي"],
        "rows": [[r.period_label, fmt_list(r.transfer_fee), fmt_list(r.exchange_spread), fmt_list(r.exchange_commission), fmt_list(r.net_by_currency)] for r in rows],
        "summary": None,
    })
    return ctx


def build_lot_profitability_context(db: OrmSession, *, doc_size: str, now: datetime, work_timezone: str) -> dict:
    from app.routers.dashboard import list_lots

    rows = list_lots(db)
    dec = currency_decimals_map(db)
    ctx = base_context(db, now=now, work_timezone=work_timezone)
    ctx.update({
        "doc_size": doc_size, "doc_title": "ربحية الدفعات", "doc_subtitle": None, "qr_data_uri": None,
        "columns": [
            "الدفعة", "مرجع السويفت", "تاريخ الوصول", "الأصلية", "سعر التكلفة", "المتبقي",
            "عدد المبيعات", "متوسط سعر البيع", "الربح", "الحالة",
        ],
        "rows": [
            [r.lot_no, r.swift_external_ref or "—", r.arrival_date.isoformat(),
             format_amount(r.original_qty, "CNY", dec), format_rate(r.cost_rate),
             format_amount(r.remaining_qty, "CNY", dec), str(r.num_sales),
             format_rate(r.weighted_avg_sale_rate) if r.weighted_avg_sale_rate is not None else "—",
             (format_amount(r.total_profit, r.profit_currency, dec) + " " + r.profit_currency) if r.profit_currency else "—",
             r.status]
            for r in rows
        ],
        "summary": None,
    })
    return ctx


def build_correspondent_balances_context(db: OrmSession, *, doc_size: str, now: datetime, work_timezone: str) -> dict:
    from app.routers.dashboard import accounts_correspondents

    body = accounts_correspondents(db)
    dec = currency_decimals_map(db)
    ctx = base_context(db, now=now, work_timezone=work_timezone)
    rows = []
    for group in body.groups:
        for account in group.accounts:
            rows.append([group.partner_name_ar, account.code, account.name_ar, account.currency_code,
                         format_amount(account.balance, account.currency_code, dec)])
    ctx.update({
        "doc_size": doc_size, "doc_title": "أرصدة المراسلين", "doc_subtitle": None, "qr_data_uri": None,
        "columns": ["الشريك", "الكود", "الحساب", "العملة", "الرصيد"],
        "rows": rows,
        "summary": [_amounts_summary_item("الإجمالي", body.totals, dec)],
    })
    return ctx


def build_chain_summary_context(db: OrmSession, *, chain_ref: str, doc_size: str, now: datetime, work_timezone: str) -> dict:
    from sqlalchemy import select

    from app.models import JournalEntry
    from app.models.enums import EntryStatus

    entries = db.execute(
        select(JournalEntry)
        .where(JournalEntry.chain_ref == chain_ref, JournalEntry.status.in_((EntryStatus.POSTED, EntryStatus.REVERSED)))
        .order_by(JournalEntry.chain_seq)
    ).scalars().all()
    dec = currency_decimals_map(db)
    ctx = base_context(db, now=now, work_timezone=work_timezone)
    ctx.update({
        "doc_size": doc_size, "doc_title": "ملخص سلسلة", "doc_subtitle": chain_ref, "qr_data_uri": None,
        # السعران منفصلان دائماً — لا سعر مركّب لسلسلة (§٢-٩: كل خطوة ربح
        # قائم بذاته)؛ مستند داخلي (لا يصل عميلاً) فعرض سعر التكلفة آمن هنا.
        "columns": ["الخطوة", "رقم القيد", "التاريخ", "النوع", "الحالة", "سعر العميل", "سعر التكلفة", "الربح"],
        "rows": [
            [f"{e.chain_seq}/{e.chain_total}" if e.chain_seq else "—", e.entry_no, e.entry_date.isoformat(),
             _OP_LABELS_AR.get(e.operation_type.value, e.operation_type.value), e.status.value,
             format_rate(e.client_rate), format_rate(e.cost_rate),
             (format_amount(e.profit_amount, e.profit_currency, dec) + " " + e.profit_currency) if e.profit_amount else "—"]
            for e in entries
        ],
        "summary": None,
    })
    return ctx


def build_liquidity_position_context(db: OrmSession, *, doc_size: str, now: datetime, work_timezone: str) -> dict:
    from app.routers.dashboard import liquidity_position

    rows = liquidity_position(db)
    dec = currency_decimals_map(db)
    ctx = base_context(db, now=now, work_timezone=work_timezone)
    ctx.update({
        "doc_size": doc_size, "doc_title": "مركز السيولة", "doc_subtitle": None, "qr_data_uri": None,
        "landscape": True,  # §٨: "PDF A4 أفقي" — تقرير عريض (عملة×موقع×٣ أعمدة)
        "columns": ["العملة", "الموقع", "الأصول", "الالتزامات", "الصافي"],
        "rows": [
            [r.currency_code, r.location_name_ar, format_amount(r.assets, r.currency_code, dec),
             format_amount(r.liabilities, r.currency_code, dec), format_amount(r.net, r.currency_code, dec)]
            for r in rows
        ],
        "summary": None,
    })
    return ctx


def build_boxes_balances_context(db: OrmSession, *, doc_size: str, now: datetime, work_timezone: str) -> dict:
    """§٨ "كشف أرصدة الصناديق" — أبناء ١١٠٠ (نقدي/مصرفي محلي في ليبيا)."""
    from app.routers.dashboard import accounts_boxes

    body = accounts_boxes(db)
    dec = currency_decimals_map(db)
    ctx = base_context(db, now=now, work_timezone=work_timezone)
    ctx.update({
        "doc_size": doc_size, "doc_title": "أرصدة الصناديق", "doc_subtitle": None, "qr_data_uri": None,
        "columns": ["الكود", "الصندوق", "العملة", "الرصيد"],
        "rows": [
            [a.code, a.name_ar, a.currency_code, format_amount(a.balance, a.currency_code, dec)]
            for a in body.accounts
        ],
        "summary": [_amounts_summary_item("الإجمالي", body.totals, dec)],
    })
    return ctx


def build_debtors_context(db: OrmSession, *, doc_size: str, now: datetime, work_timezone: str) -> dict:
    from app.routers.reports import debtors

    modes = {"NONE": "بلا ائتمان", "LIMIT": "حد بمبلغ", "UNLIMITED": "بلا سقف"}
    dec = currency_decimals_map(db)
    rows = debtors(db)
    ctx = base_context(db, now=now, work_timezone=work_timezone)
    ctx.update({
        "doc_size": doc_size, "doc_title": "العملاء المدينون", "doc_subtitle": "كل رصيد سالب، لكل عملة وموقع — الأكبر أولاً",
        "qr_data_uri": None,
        "columns": ["العميل", "الكود", "العملة", "الموقع", "الدين", "الائتمان", "آخر حركة"],
        "rows": [
            [r.client_name, r.client_code, r.currency_code, r.location_code or "—", format_amount(r.debt, r.currency_code, dec), modes.get(r.credit_mode, r.credit_mode),
             r.last_activity.isoformat() if r.last_activity else "—"]
            for r in rows
        ],
        "summary": None,
    })
    return ctx
