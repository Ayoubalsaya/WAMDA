"""البحث الذكي (§٧-١٠) — يستقبل مُرشِّحات **مُهيكَلة** لا نصاً خاماً
يُعاد تحليله خادمياً: الواجهة تُحلِّل ما يكتبه المستخدم (`أحمد` ·
`WMD-2026-000123` · `CHN-2026-000042` · `>5000` · `USD` · نطاق تاريخ ·
`صرافة` · `@مستخدم`) إلى رقائق مُهيكَلة قابلة للإزالة فرداً فرداً، ثم
تُرسِلها كمُدخَلات صريحة هنا — تفادياً لتكرار منطق التحليل مرتين (مرة
لعرض الرقائق، ومرة لتفسير النص خادمياً) وتناقضهما المحتمل.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.models import Client, JournalEntry, JournalLine, User
from app.models.enums import EntryStatus, OperationType
from app.schemas.search import SearchResultRow
from app.security.deps import require_password_changed

router = APIRouter(tags=["search"], dependencies=[Depends(require_password_changed)])


@router.get("/search", response_model=list[SearchResultRow])
def search(
    q: Optional[str] = Query(default=None, description="اسم عميل أو بيان — مطابقة جزئية"),
    entry_no: Optional[str] = Query(default=None),
    chain_ref: Optional[str] = Query(default=None),
    min_amount: Optional[Decimal] = Query(default=None, ge=0),
    currency: Optional[str] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    operation_type: Optional[str] = Query(default=None),
    username: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    include_reversed: bool = Query(default=False, description="أظهر الملغاة — مخفية افتراضياً كبقية القوائم"),
    db: OrmSession = Depends(get_db),
) -> list[SearchResultRow]:
    if include_reversed:
        query = select(JournalEntry).where(JournalEntry.status.in_((EntryStatus.POSTED, EntryStatus.REVERSED)))
    else:
        query = select(JournalEntry).where(
            JournalEntry.status == EntryStatus.POSTED, JournalEntry.reverses_entry_id.is_(None)
        )

    if entry_no:
        query = query.where(JournalEntry.entry_no.ilike(f"%{entry_no}%"))
    if chain_ref:
        query = query.where(JournalEntry.chain_ref.ilike(f"%{chain_ref}%"))
    if operation_type and operation_type in OperationType.__members__:
        query = query.where(JournalEntry.operation_type == OperationType[operation_type])
    if date_from:
        query = query.where(JournalEntry.entry_date >= date_from)
    if date_to:
        query = query.where(JournalEntry.entry_date <= date_to)
    if username:
        matching_user_ids = db.execute(
            select(User.id).where(User.username.ilike(f"%{username}%"))
        ).scalars().all()
        query = query.where(JournalEntry.created_by.in_(matching_user_ids or [-1]))
    if q:
        matching_client_ids = db.execute(
            select(Client.id).where(or_(Client.name_ar.ilike(f"%{q}%"), Client.search_name.ilike(f"%{q}%")))
        ).scalars().all()
        query = query.where(
            or_(
                JournalEntry.client_id.in_(matching_client_ids or [-1]),
                JournalEntry.description.ilike(f"%{q}%"),
            )
        )
    if currency:
        entry_ids_by_currency = db.execute(
            select(JournalLine.entry_id).where(JournalLine.currency_code == currency).distinct()
        ).scalars().all()
        query = query.where(JournalEntry.id.in_(entry_ids_by_currency or [-1]))
    if min_amount is not None:
        entry_ids_by_amount = db.execute(
            select(JournalLine.entry_id).where(
                or_(JournalLine.debit >= min_amount, JournalLine.credit >= min_amount)
            ).distinct()
        ).scalars().all()
        query = query.where(JournalEntry.id.in_(entry_ids_by_amount or [-1]))

    entries = db.execute(query.order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc()).limit(limit)).scalars().all()
    if not entries:
        return []

    entry_ids = [e.id for e in entries]
    lines = db.execute(select(JournalLine).where(JournalLine.entry_id.in_(entry_ids))).scalars().all()
    from app.models import Account

    account_ids = {ln.account_id for ln in lines}
    accounts = {a.id: a for a in db.execute(select(Account).where(Account.id.in_(account_ids))).scalars().all()}
    lines_by_entry: dict[int, list[JournalLine]] = {}
    for ln in lines:
        lines_by_entry.setdefault(ln.entry_id, []).append(ln)

    client_ids = {e.client_id for e in entries if e.client_id is not None}
    clients = {c.id: c for c in db.execute(select(Client).where(Client.id.in_(client_ids))).scalars().all()} if client_ids else {}

    result = []
    for e in entries:
        entry_lines = sorted(lines_by_entry.get(e.id, []), key=lambda ln: ln.line_no)
        result.append(
            SearchResultRow(
                id=e.id, entry_no=e.entry_no, entry_date=e.entry_date, operation_type=e.operation_type.value,
                status=e.status.value, description=e.description, note=e.note, replaces_entry_id=e.replaces_entry_id,
                client_name_ar=clients[e.client_id].name_ar if e.client_id in clients else None,
                profit_amount=e.profit_amount, profit_currency=e.profit_currency, chain_ref=e.chain_ref,
                lines=[
                    {
                        "account_code": accounts[ln.account_id].code, "account_name_ar": accounts[ln.account_id].name_ar,
                        "currency_code": ln.currency_code, "debit": ln.debit, "credit": ln.credit, "memo": ln.memo,
                    }
                    for ln in entry_lines
                ],
            )
        )
    return result
