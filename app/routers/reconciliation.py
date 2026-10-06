"""المطابقة (§٧-٩) — دفترك مقابل كشف المراسل: إدخال كشف · مطابقة تلقائية
بالمبلغ والتاريخ التقريبي · مطابقة يدوية · إبراز الفروق. التسوية الفعلية
لأي فرق تبقى عبر عملية `ADJUSTMENT` القائمة في دفتر اليومية (المرحلة ٧)
— هذا الملف لا يُنشئ قيوداً، فقط يربط سطر الكشف بالقيد المطابق (تلقائياً
أو يدوياً بمعرّف قيد ADJUSTMENT بعد ترحيله).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.config import settings
from app.database import get_db
from app.engine import reconciliation as recon_engine
from app.engine.clock import system_clock
from app.engine.operations import adjustment as adjustment_op
from app.routers.operations import _run as _run_engine
from app.models import Account, JournalEntry, JournalLine, Partner, PartnerStatement, PartnerStatementLine, User
from app.models.enums import EntryStatus, ReconciliationStatus
from app.schemas.reconciliation import (
    AdjustLineRequest,
    AutoMatchResponse,
    CreatePartnerStatementRequest,
    ManualMatchRequest,
    PartnerStatementDetail,
    PartnerStatementSummary,
    ResolveLineRequest,
    StatementLineOut,
    YourLedgerEntryOut,
)
from app.security import audit
from app.security.deps import require_role, verify_csrf
from app.security.permissions import Action

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])

_MATCH_DATE_TOLERANCE = timedelta(days=3)


def _get_statement_or_404(db: OrmSession, statement_id: int) -> PartnerStatement:
    row = db.get(PartnerStatement, statement_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا كشف بالمعرّف {statement_id}")
    return row


def _line_out(db: OrmSession, line: PartnerStatementLine) -> StatementLineOut:
    entry_no = None
    if line.matched_entry_id is not None:
        entry = db.get(JournalEntry, line.matched_entry_id)
        entry_no = entry.entry_no if entry else None
    return StatementLineOut(
        id=line.id, value_date=line.value_date, description=line.description, amount=line.amount,
        status=line.status.value, matched_entry_id=line.matched_entry_id, matched_entry_no=entry_no,
    )


def _detail(db: OrmSession, statement: PartnerStatement, partner_name: str) -> PartnerStatementDetail:
    lines = db.execute(
        select(PartnerStatementLine).where(PartnerStatementLine.statement_id == statement.id).order_by(PartnerStatementLine.value_date)
    ).scalars().all()
    # جانب "دفترك" — الاتجاه المعاكس: قيودك التي تمسّ حساب المراسل
    ledger = recon_engine.partner_ledger_entries(
        db, partner_id=statement.partner_id,
        period_from=statement.period_from, period_to=statement.period_to,
    )
    line_outs = [_line_out(db, ln) for ln in lines]
    your_entries = [
        YourLedgerEntryOut(
            entry_id=e.entry_id, entry_no=e.entry_no, entry_date=e.entry_date,
            operation_type=e.operation_type, description=e.description,
            amount=e.amount, matched_line_id=e.matched_line_id,
        )
        for e in ledger
    ]
    return PartnerStatementDetail(
        id=statement.id, partner_id=statement.partner_id, partner_name_ar=partner_name,
        period_from=statement.period_from, period_to=statement.period_to, imported_at=statement.imported_at,
        lines=line_outs,
        your_entries=your_entries,
        unmatched_line_count=sum(1 for lo in line_outs if lo.status == ReconciliationStatus.OPEN.value),
        unmatched_entry_count=sum(1 for ye in your_entries if ye.matched_line_id is None),
    )


@router.post("/statements", response_model=PartnerStatementDetail, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_csrf)])
def create_statement(
    payload: CreatePartnerStatementRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.RECONCILIATION)),
) -> PartnerStatementDetail:
    partner = db.get(Partner, payload.partner_id)
    if partner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا شريك بالمعرّف {payload.partner_id}")
    statement = PartnerStatement(partner_id=partner.id, period_from=payload.period_from, period_to=payload.period_to)
    db.add(statement)
    db.flush()
    for line in payload.lines:
        db.add(PartnerStatementLine(
            statement_id=statement.id, value_date=line.value_date, description=line.description,
            amount=line.amount, status=ReconciliationStatus.OPEN,
        ))
    audit.log_user_write(
        db, current_user, action="PARTNER_STATEMENT_CREATED", entity="partner_statements", entity_id=statement.id,
        after={"partner_id": partner.id, "period_from": str(payload.period_from), "period_to": str(payload.period_to), "lines": len(payload.lines)},
    )
    db.commit()
    return _detail(db, statement, partner.name_ar)


@router.get("/statements", response_model=list[PartnerStatementSummary])
def list_statements(
    db: OrmSession = Depends(get_db), current_user: User = Depends(require_role(Action.RECONCILIATION)),
) -> list[PartnerStatementSummary]:
    statements = db.execute(select(PartnerStatement).order_by(PartnerStatement.imported_at.desc())).scalars().all()
    if not statements:
        return []
    partner_ids = {s.partner_id for s in statements}
    partners = {p.id: p for p in db.execute(select(Partner).where(Partner.id.in_(partner_ids))).scalars().all()}
    statement_ids = [s.id for s in statements]
    all_lines = db.execute(select(PartnerStatementLine).where(PartnerStatementLine.statement_id.in_(statement_ids))).scalars().all()
    lines_by_statement: dict[int, list[PartnerStatementLine]] = {}
    for ln in all_lines:
        lines_by_statement.setdefault(ln.statement_id, []).append(ln)
    return [
        PartnerStatementSummary(
            id=s.id, partner_id=s.partner_id, partner_name_ar=partners[s.partner_id].name_ar if s.partner_id in partners else "?",
            period_from=s.period_from, period_to=s.period_to, imported_at=s.imported_at,
            total_lines=len(lines_by_statement.get(s.id, [])),
            open_lines=sum(1 for ln in lines_by_statement.get(s.id, []) if ln.status == ReconciliationStatus.OPEN),
        )
        for s in statements
    ]


@router.get("/statements/{statement_id}", response_model=PartnerStatementDetail)
def get_statement(
    statement_id: int, db: OrmSession = Depends(get_db), current_user: User = Depends(require_role(Action.RECONCILIATION)),
) -> PartnerStatementDetail:
    statement = _get_statement_or_404(db, statement_id)
    partner = db.get(Partner, statement.partner_id)
    return _detail(db, statement, partner.name_ar if partner else "?")


@router.post("/statements/{statement_id}/auto-match", response_model=AutoMatchResponse, dependencies=[Depends(verify_csrf)])
def auto_match(
    statement_id: int, db: OrmSession = Depends(get_db), current_user: User = Depends(require_role(Action.RECONCILIATION)),
) -> AutoMatchResponse:
    """مطابقة تلقائية: سطر كشف مقابل سطر قيد يمسّ أحد حسابات هذا المراسل،
    بنفس المبلغ (مطلقاً — دفترك قد يُسجِّله مديناً أو دائناً حسب الاتجاه)
    ضمن ±٣ أيام من تاريخ القيمة. لا مطابقة إن تعدَّد المرشِّحون (غموض حقيقي
    يستحق مراجعة يدوية لا تخميناً)."""
    statement = _get_statement_or_404(db, statement_id)
    partner_account_ids = db.execute(select(Account.id).where(Account.partner_id == statement.partner_id)).scalars().all()
    if not partner_account_ids:
        return AutoMatchResponse(matched_count=0, statement=_detail(db, statement, _partner_name(db, statement.partner_id)))

    already_matched_entry_ids = set(
        db.execute(
            select(PartnerStatementLine.matched_entry_id).where(PartnerStatementLine.matched_entry_id.isnot(None))
        ).scalars().all()
    )
    open_lines = db.execute(
        select(PartnerStatementLine).where(
            PartnerStatementLine.statement_id == statement.id, PartnerStatementLine.status == ReconciliationStatus.OPEN,
        )
    ).scalars().all()

    matched_count = 0
    for line in open_lines:
        date_from = line.value_date - _MATCH_DATE_TOLERANCE
        date_to = line.value_date + _MATCH_DATE_TOLERANCE
        candidates = db.execute(
            select(JournalLine.entry_id)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                JournalLine.account_id.in_(partner_account_ids),
                JournalEntry.status == EntryStatus.POSTED,
                JournalEntry.entry_date >= date_from, JournalEntry.entry_date <= date_to,
                (JournalLine.debit == abs(line.amount)) | (JournalLine.credit == abs(line.amount)),
            )
            .distinct()
        ).scalars().all()
        eligible = [c for c in candidates if c not in already_matched_entry_ids]
        if len(eligible) == 1:
            line.matched_entry_id = eligible[0]
            line.status = ReconciliationStatus.RESOLVED
            already_matched_entry_ids.add(eligible[0])
            matched_count += 1
    audit.log_user_write(
        db, current_user, action="PARTNER_STATEMENT_AUTO_MATCHED", entity="partner_statements", entity_id=statement.id,
        after={"matched_count": matched_count},
    )
    db.commit()
    return AutoMatchResponse(matched_count=matched_count, statement=_detail(db, statement, _partner_name(db, statement.partner_id)))


def _line_audit_view(line: PartnerStatementLine) -> dict:
    return {"status": line.status.value, "matched_entry_id": line.matched_entry_id, "amount": str(line.amount)}


def _partner_name(db: OrmSession, partner_id: int) -> str:
    partner = db.get(Partner, partner_id)
    return partner.name_ar if partner else "?"


@router.patch("/statements/{statement_id}/lines/{line_id}/match", response_model=StatementLineOut, dependencies=[Depends(verify_csrf)])
def manual_match(
    statement_id: int, line_id: int, payload: ManualMatchRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.RECONCILIATION)),
) -> StatementLineOut:
    line = _get_line_or_404(db, statement_id, line_id)
    before = _line_audit_view(line)
    entry = db.get(JournalEntry, payload.entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا قيد بالمعرّف {payload.entry_id}")
    line.matched_entry_id = entry.id
    line.status = ReconciliationStatus.RESOLVED
    audit.log_user_write(
        db, current_user, action="STATEMENT_LINE_MATCHED", entity="partner_statement_lines", entity_id=line.id,
        before=before, after=_line_audit_view(line),
    )
    db.commit()
    return _line_out(db, line)


@router.patch("/statements/{statement_id}/lines/{line_id}/resolve", response_model=StatementLineOut, dependencies=[Depends(verify_csrf)])
def resolve_line(
    statement_id: int, line_id: int, payload: ResolveLineRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.RECONCILIATION)),
) -> StatementLineOut:
    """تسوية الفرق — عادة بعد ترحيل ADJUSTMENT من دفتر اليومية يعالج
    الفرق فعلياً؛ `matched_entry_id` هنا اختياري (قد لا يوجد قيد مطابق
    مباشر، فقط قرار إداري بإغلاق السطر)."""
    line = _get_line_or_404(db, statement_id, line_id)
    before = _line_audit_view(line)
    if payload.matched_entry_id is not None:
        entry = db.get(JournalEntry, payload.matched_entry_id)
        if entry is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا قيد بالمعرّف {payload.matched_entry_id}")
        line.matched_entry_id = entry.id
    line.status = ReconciliationStatus.RESOLVED
    audit.log_user_write(
        db, current_user, action="STATEMENT_LINE_RESOLVED", entity="partner_statement_lines", entity_id=line.id,
        before=before, after=_line_audit_view(line),
    )
    db.commit()
    return _line_out(db, line)


def _get_line_or_404(db: OrmSession, statement_id: int, line_id: int) -> PartnerStatementLine:
    line = db.get(PartnerStatementLine, line_id)
    if line is None or line.statement_id != statement_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا سطر بالمعرّف {line_id} في هذا الكشف")
    return line


@router.post(
    "/statements/{statement_id}/lines/{line_id}/adjust", response_model=StatementLineOut,
    dependencies=[Depends(verify_csrf)],
)
def adjust_line(
    statement_id: int, line_id: int, payload: AdjustLineRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.RECONCILIATION)),
) -> StatementLineOut:
    """تسوية فرق سطر كشف بقيد `ADJUSTMENT` يُرحَّل هنا مباشرة ويُربَط
    بالسطر — بدل ترحيله يدوياً في دفتر اليومية ثم لصق معرّفه. **السبب
    إلزامي** (§٥-١٢، يُفرَض في المخطّط وفي محرّك `adjustment`). السطر يجب
    أن يكون `OPEN` (فرق غير مسوّى) — تسوية سطر مُسوّى مسبقاً مرفوضة."""
    line = _get_line_or_404(db, statement_id, line_id)
    before = _line_audit_view(line)
    if line.status != ReconciliationStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, "هذا السطر مُسوّى بالفعل")

    statement = _get_statement_or_404(db, statement_id)
    account = db.execute(select(Account).where(Account.code == payload.account_code)).scalar_one_or_none()
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا حساب بالكود {payload.account_code}")
    if account.partner_id != statement.partner_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "حساب التسوية يجب أن يخصّ نفس المراسل صاحب الكشف",
        )

    now = system_clock()
    # نفس ترجمة أخطاء المحرّك المستخدَمة في /operations (٤٠٤/٤٠٩/٤٢٢…) —
    # بلا `db.rollback()` صريح (get_db يُغلق الجلسة، والالتزام على النجاح فقط)
    entry = _run_engine(lambda: adjustment_op.execute(
        db, account_code=payload.account_code, currency_code=payload.currency_code,
        amount=payload.amount, is_debit=payload.is_debit, reason=payload.reason,
        work_timezone=settings.work_timezone, created_by=current_user.id, now=now,
        idempotency_key=f"recon-adjust-{line_id}-{uuid.uuid4()}",
    ))

    line.matched_entry_id = entry.id
    line.status = ReconciliationStatus.RESOLVED
    audit.log_user_write(
        db, current_user, action="STATEMENT_LINE_ADJUSTED", entity="partner_statement_lines", entity_id=line.id,
        before=before, after=_line_audit_view(line),
    )
    db.commit()
    return _line_out(db, line)
