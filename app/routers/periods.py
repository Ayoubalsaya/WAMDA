"""إقفال الفترات الشهرية وفتحها + إقفال الفترة التأسيسية (§٩ المرحلة ١١)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.documents.formatting import currency_decimals_map, format_amount
from app.engine import opening, periods
from app.engine.clock import system_clock
from app.models import Account, FoundingPeriod, OpeningBalance, Period, User
from app.schemas.periods import (
    ClosePeriodRequest,
    CloseFoundingPeriodRequest,
    FoundingPeriodStatus,
    OpeningBalanceRow,
    PeriodRow,
    ReopenPeriodRequest,
)
from app.security import audit
from app.security.deps import require_password_changed, require_role, verify_csrf
from app.security.permissions import Action
from app.models.enums import SessionSubjectType

router = APIRouter(prefix="/periods", tags=["periods"], dependencies=[Depends(require_password_changed)])


def _period_row(period: Period, users_by_id: dict[int, User]) -> PeriodRow:
    closer = users_by_id.get(period.closed_by) if period.closed_by else None
    return PeriodRow(
        year=period.year, month=period.month, is_closed=period.is_closed,
        closed_by_username=closer.username if closer else None, closed_at=period.closed_at,
    )


@router.get("", response_model=list[PeriodRow])
def list_periods(db: OrmSession = Depends(get_db)) -> list[PeriodRow]:
    rows = db.execute(select(Period).order_by(Period.year.desc(), Period.month.desc())).scalars().all()
    user_ids = {r.closed_by for r in rows if r.closed_by is not None}
    users_by_id = {u.id: u for u in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()} if user_ids else {}
    return [_period_row(r, users_by_id) for r in rows]


@router.post("/close", response_model=PeriodRow, dependencies=[Depends(verify_csrf)])
def close_period(
    payload: ClosePeriodRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.CLOSE_PERIOD)),
) -> PeriodRow:
    try:
        period = periods.close_period(db, year=payload.year, month=payload.month, closed_by=current_user.id, now=system_clock())
    except periods.PeriodAlreadyClosedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=current_user.id, action="PERIOD_CLOSED", entity="periods",
        after={"year": payload.year, "month": payload.month},
    )
    db.commit()
    return _period_row(period, {current_user.id: current_user})


@router.post("/reopen", response_model=PeriodRow, dependencies=[Depends(verify_csrf)])
def reopen_period(
    payload: ReopenPeriodRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.REOPEN_CLOSED_PERIOD)),
) -> PeriodRow:
    try:
        period = periods.reopen_period(db, year=payload.year, month=payload.month)
    except periods.PeriodNotClosedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=current_user.id, action="PERIOD_REOPENED", entity="periods",
        after={"year": payload.year, "month": payload.month},
    )
    db.commit()
    users_by_id = {period.closed_by: db.get(User, period.closed_by)} if period.closed_by else {}
    return _period_row(period, users_by_id)


@router.get("/founding", response_model=FoundingPeriodStatus)
def founding_period_status(db: OrmSession = Depends(get_db)) -> FoundingPeriodStatus:
    founding = db.get(FoundingPeriod, 1)
    if founding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "لا صف founding_period — بيانات التهيئة غير مكتملة")
    closer = db.get(User, founding.closed_by) if founding.closed_by else None
    suspense = opening.total_suspense_balance(db)
    dec = currency_decimals_map(db)
    return FoundingPeriodStatus(
        is_open=founding.is_open, closed_at=founding.closed_at,
        closed_by_username=closer.username if closer else None,
        suspense_balance_by_currency={ccy: format_amount(bal, ccy, dec) for ccy, bal in suspense.items()},
    )


@router.get("/opening-balances", response_model=list[OpeningBalanceRow])
def list_opening_balances(
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.OPENING_BALANCES)),
) -> list[OpeningBalanceRow]:
    """كل الأرصدة الافتتاحية المُدخَلة — لمراجعة ما أُدخِل قبل إقفال الفترة
    التأسيسية (المرحلة ١٤، التشغيل المتوازي). مدير فقط."""
    rows = db.execute(select(OpeningBalance).order_by(OpeningBalance.created_at)).scalars().all()
    if not rows:
        return []
    acct_ids = {r.account_id for r in rows} | {r.contra_account_id for r in rows}
    accts = {a.id: a for a in db.execute(select(Account).where(Account.id.in_(acct_ids))).scalars().all()}
    users = {
        u.id: u for u in db.execute(select(User).where(User.id.in_({r.approved_by for r in rows}))).scalars().all()
    }
    dec = currency_decimals_map(db)
    out = []
    for r in rows:
        acct = accts.get(r.account_id)
        contra = accts.get(r.contra_account_id)
        out.append(OpeningBalanceRow(
            id=r.id,
            account_code=acct.code if acct else "?",
            account_name_ar=acct.name_ar if acct else "?",
            currency_code=r.currency_code,
            amount=format_amount(r.amount, r.currency_code, dec),
            as_of_date=r.as_of_date,
            source_type=r.source_type.value,
            confidence=r.confidence.value,
            source_note=r.source_note,
            contra_account_code=contra.code if contra else "?",
            approved_by_username=users[r.approved_by].username if r.approved_by in users else None,
        ))
    return out


@router.post("/founding/close", response_model=FoundingPeriodStatus, dependencies=[Depends(verify_csrf)])
def close_founding_period(
    payload: CloseFoundingPeriodRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.OPENING_BALANCES)),
) -> FoundingPeriodStatus:
    try:
        founding = opening.close_founding_period(
            db, closed_by=current_user.id, now=system_clock(),
            acknowledged_remaining_suspense=payload.acknowledged_remaining_suspense,
        )
    except opening.FoundingPeriodAlreadyClosedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except opening.SuspenseBalanceAcknowledgmentRequiredError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=current_user.id, action="FOUNDING_PERIOD_CLOSED",
        entity="founding_period", entity_id=1,
        after={"acknowledged_remaining_suspense": payload.acknowledged_remaining_suspense},
    )
    db.commit()
    dec = currency_decimals_map(db)
    return FoundingPeriodStatus(
        is_open=founding.is_open, closed_at=founding.closed_at, closed_by_username=current_user.username,
        suspense_balance_by_currency={
            ccy: format_amount(bal, ccy, dec) for ccy, bal in opening.total_suspense_balance(db).items()
        },
    )
