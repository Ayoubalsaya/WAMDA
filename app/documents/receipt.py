"""إيصال عملية (قبض/تسليم/صرافة/تحويل...) — §٨. يعمل لأي عملية تخصّ
عميلاً، لا RECEIPT/PAYMENT فقط (العميل يحتاج إيصالاً لأي عملية لمسّت
حسابه). REMIT_OUT تحديداً يضيف لقطة الوجهة (اسم/رقم حساب/بنك) من
`RemitOutDestination` — لقطة لحظة الترحيل، لا تتأثر بتعديل المستفيد لاحقاً.

**cost_rate لا يصل هذا الملف إطلاقاً** — لا يُقرأ من `JournalEntry` هنا،
فلا حاجة لحجبه لاحقاً في القالب (نفس مبدأ بوابة العميل، المرحلة ٩: يُحجَب
عند مصدر البيانات لا في العرض).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.documents.common import base_context
from app.models import Account, Client, JournalEntry, JournalLine, Location, RemitOutDestination
from app.models.enums import EntryStatus

_OP_LABELS_AR: dict[str, str] = {
    "RECEIPT": "إيصال قبض", "PAYMENT": "إيصال تسليم", "EXCHANGE": "إيصال صرافة",
    "CASH_TRANSFER": "إيصال تحويل", "LOCAL_MOVE": "إيصال نقل داخلي", "REMIT_OUT": "إيصال إرسال لمستفيد",
    "SWIFT_OUT": "إيصال سويفت", "SWIFT_IN": "إيصال سويفت وصول", "SWIFT_RETURN": "إيصال سويفت مرتجع",
    "EXPENSE": "إيصال مصروف", "OPENING": "إيصال رصيد افتتاحي", "ADJUSTMENT": "إيصال تسوية",
}


def _client_account_balance_before_after(
    db: OrmSession, *, account: Account, entry: JournalEntry,
) -> tuple[Decimal, Decimal]:
    """رصيد حساب العميل قبل وبعد هذا القيد بالذات — نفس منطق الرصيد المتحرك
    في `compute_client_statement` (المرحلة ٥/٩)، هنا لقيد واحد بعينه."""
    before_rows = db.execute(
        select(JournalLine.debit, JournalLine.credit, JournalEntry.entry_date, JournalEntry.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            JournalLine.account_id == account.id,
            JournalEntry.status.in_((EntryStatus.POSTED, EntryStatus.REVERSED)),
            (JournalEntry.entry_date < entry.entry_date)
            | ((JournalEntry.entry_date == entry.entry_date) & (JournalEntry.id < entry.id)),
        )
    ).all()
    before = sum((r.credit - r.debit for r in before_rows), Decimal("0"))

    this_entry_lines = db.execute(
        select(JournalLine).where(JournalLine.account_id == account.id, JournalLine.entry_id == entry.id)
    ).scalars().all()
    delta = sum((line.credit - line.debit for line in this_entry_lines), Decimal("0"))
    return before, before + delta


def build_receipt_context(db: OrmSession, *, entry_id: int, doc_size: str, now: datetime, work_timezone: str) -> dict:
    entry = db.get(JournalEntry, entry_id)
    if entry is None or entry.status not in (EntryStatus.POSTED, EntryStatus.REVERSED):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "لا قيد مُرحَّل بهذا المعرّف")
    if entry.client_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "هذا القيد لا يخصّ عميلاً — لا إيصال له")

    client = db.get(Client, entry.client_id)

    client_lines = db.execute(
        select(JournalLine).where(JournalLine.entry_id == entry.id, JournalLine.account_id.in_(
            select(Account.id).where(Account.client_id == entry.client_id)
        ))
    ).scalars().all()

    balances = []
    for line in client_lines:
        account = db.get(Account, line.account_id)
        before, after = _client_account_balance_before_after(db, account=account, entry=entry)
        location = db.get(Location, account.location_id) if account.location_id else None
        balances.append({
            "currency_code": account.currency_code,
            "location_name": location.name_ar if location else "",
            "before": before,
            "after": after,
            "debit": line.debit,
            "credit": line.credit,
        })

    destination = None
    if entry.operation_type.value == "REMIT_OUT":
        dest_row = db.execute(
            select(RemitOutDestination).where(RemitOutDestination.entry_id == entry.id)
        ).scalar_one_or_none()
        if dest_row is not None:
            destination = {
                "beneficiary_name": dest_row.beneficiary_name_snapshot,
                "account_number": dest_row.account_number_snapshot,
                "bank_name": dest_row.bank_name_snapshot,
                "currency_code": dest_row.currency_code,
            }

    ctx = base_context(db, now=now, work_timezone=work_timezone)
    ctx.update({
        "doc_size": doc_size,
        "doc_title": _OP_LABELS_AR.get(entry.operation_type.value, "إيصال عملية"),
        "doc_subtitle": f"{entry.entry_no} — {entry.entry_date.isoformat()}",
        "qr_data_uri": None,  # يُضبَط في الراوتر (يحتاج رابط تحقق كامل)
        "client_name": client.name_ar if client else "",
        "client_code": client.code if client else "",
        "description": entry.description,
        "balances": balances,
        "destination": destination,
    })
    return ctx
