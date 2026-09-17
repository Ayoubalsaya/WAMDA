"""كشف حساب مطبوع — عميل (§٨ "كشف حساب عميل") أو حساب نظامي/أساسي (§٨
"كشف حساب أساسي": صندوق/بنك/مراسل، لا عميل). نفس منطق الرصيد المتحرك في
`compute_client_statement` (المرحلة ٥/٩) بالضبط، هنا مُجرَّد لأي حساب
واحد بمعرّفه مباشرة — لا استلزام أن يكون حساب عميل."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.documents.common import base_context
from app.documents.formatting import currency_decimals_map, format_amount, format_rate
from app.models import Account, Client, JournalEntry, JournalLine, Location
from app.models.enums import EntryStatus

_OP_LABELS_AR: dict[str, str] = {
    "RECEIPT": "قبض", "PAYMENT": "صرف", "EXCHANGE": "صرافة", "CASH_TRANSFER": "تحويل بعمولة",
    "LOCAL_MOVE": "نقل داخلي", "REMIT_OUT": "إرسال لمستفيد", "SWIFT_OUT": "سويفت خروج", "SWIFT_IN": "سويفت وصول",
    "SWIFT_RETURN": "سويفت مرتجع", "EXPENSE": "مصروف", "OPENING": "رصيد افتتاحي", "ADJUSTMENT": "تسوية",
}


def _running_balance(
    db: OrmSession, *, account: Account, date_from: Optional[date], date_to: Optional[date],
    show_cost_rate: bool = False,
) -> tuple[Decimal, list[dict], Decimal]:
    """`show_cost_rate=False` (كشف حساب عميل — العميل يرى سعره فقط، أبداً
    التكلفة) يستبعد cost_rate من الصف نفسه لا في القالب فقط — نفس مبدأ
    `receipt.py`: يُحجب عند مصدر البيانات، لا عرضاً مشروطاً لاحقاً قابلاً
    للكسر بتعديل قالب مستقبلي. `show_cost_rate=True` حصراً لكشف الحساب
    الأساسي/كشف المراسل (داخلي، لا يصل عميلاً)."""
    if date_from is not None:
        opening = db.execute(
            select(JournalLine.credit, JournalLine.debit)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                JournalLine.account_id == account.id,
                JournalEntry.status.in_((EntryStatus.POSTED, EntryStatus.REVERSED)),
                JournalEntry.entry_date < date_from,
            )
        ).all()
        opening_balance = sum((r.credit - r.debit for r in opening), Decimal("0"))
    else:
        opening_balance = Decimal("0")

    query = (
        select(JournalEntry, JournalLine)
        .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .where(JournalLine.account_id == account.id, JournalEntry.status.in_((EntryStatus.POSTED, EntryStatus.REVERSED)))
        .order_by(JournalEntry.entry_date, JournalEntry.id)
    )
    if date_from is not None:
        query = query.where(JournalEntry.entry_date >= date_from)
    if date_to is not None:
        query = query.where(JournalEntry.entry_date <= date_to)

    running = opening_balance
    rows = []
    for entry, line in db.execute(query).all():
        running = running + line.credit - line.debit
        row = {
            "entry_no": entry.entry_no, "entry_date": entry.entry_date.isoformat(),
            "operation_type": _OP_LABELS_AR.get(entry.operation_type.value, entry.operation_type.value),
            "description": entry.description, "debit": line.debit, "credit": line.credit, "running": running,
            "note": entry.note,
            "client_rate": format_rate(entry.client_rate) if entry.client_rate is not None else None,
        }
        if show_cost_rate:
            row["cost_rate"] = format_rate(entry.cost_rate) if entry.cost_rate is not None else None
        rows.append(row)
    return opening_balance, rows, running


def build_client_statement_context(
    db: OrmSession, *, client_id: int, currency: str, location: str, doc_size: str,
    date_from: Optional[date], date_to: Optional[date], now: datetime, work_timezone: str,
) -> dict:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا عميل بالمعرّف {client_id}")
    location_row = db.execute(select(Location).where(Location.code == location)).scalar_one_or_none()
    if location_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا موقع بالكود {location}")
    account = db.execute(
        select(Account).where(
            Account.client_id == client_id, Account.currency_code == currency, Account.location_id == location_row.id
        )
    ).scalar_one_or_none()
    dec = currency_decimals_map(db)

    ctx = base_context(db, now=now, work_timezone=work_timezone)
    ctx.update({
        "doc_size": doc_size, "doc_title": "كشف حساب عميل",
        "doc_subtitle": f"{client.name_ar} — {currency} — {location_row.name_ar}", "qr_data_uri": None,
        "opening_balance": format_amount(Decimal("0"), currency, dec), "closing_balance": format_amount(Decimal("0"), currency, dec),
        "rows": [], "show_cost_rate": False,
    })
    if account is None:
        return ctx

    opening, rows, closing = _running_balance(db, account=account, date_from=date_from, date_to=date_to)
    ctx["opening_balance"] = format_amount(opening, currency, dec)
    ctx["closing_balance"] = format_amount(closing, currency, dec)
    ctx["rows"] = [
        {**r, "debit": format_amount(r["debit"], currency, dec) if r["debit"] else "—",
         "credit": format_amount(r["credit"], currency, dec) if r["credit"] else "—",
         "running": format_amount(r["running"], currency, dec)}
        for r in rows
    ]
    return ctx


def build_account_statement_context(
    db: OrmSession, *, account_code: str, doc_size: str, date_from: Optional[date], date_to: Optional[date],
    now: datetime, work_timezone: str,
) -> dict:
    account = db.execute(select(Account).where(Account.code == account_code)).scalar_one_or_none()
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا حساب بالكود {account_code}")
    dec = currency_decimals_map(db)
    # داخلي دائماً (حساب نظامي/مراسل، لا عميل) — سعر التكلفة مسموح هنا.
    opening, rows, closing = _running_balance(db, account=account, date_from=date_from, date_to=date_to, show_cost_rate=True)

    ctx = base_context(db, now=now, work_timezone=work_timezone)
    ctx.update({
        "doc_size": doc_size, "doc_title": "كشف حساب",
        "doc_subtitle": f"{account.name_ar} ({account.code})", "qr_data_uri": None,
        "opening_balance": format_amount(opening, account.currency_code, dec),
        "closing_balance": format_amount(closing, account.currency_code, dec),
        "show_cost_rate": True,
        "rows": [
            {**r, "debit": format_amount(r["debit"], account.currency_code, dec) if r["debit"] else "—",
             "credit": format_amount(r["credit"], account.currency_code, dec) if r["credit"] else "—",
             "running": format_amount(r["running"], account.currency_code, dec)}
            for r in rows
        ],
    })
    return ctx
