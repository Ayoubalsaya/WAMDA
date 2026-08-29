"""مسارات الاثنتي عشرة عملية (§٤) — تُغلِّف `app/engine/operations/*` بلا أي
منطق محاسبي هنا. كل مسار: `Action.POST_ENTRY` (مدير/محاسب) + CSRF +
`Idempotency-Key` إلزامية (§٦-٤، تُولَّد في المتصفح عند بدء ملء النموذج).
"""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.engine import chain
from app.engine import clock as _clock
from app.engine.accounts_repo import AccountNotFoundError, InvalidClientLocationError, get_or_create_client_account
from app.engine.clock import system_clock
from app.engine.idempotency import IdempotencyConflict
from app.engine.operations import (
    adjustment as adjustment_op,
    cash_transfer as cash_transfer_op,
    exchange as exchange_op,
    expense as expense_op,
    local_move as local_move_op,
    opening_balance as opening_op,
    payment as payment_op,
    receipt as receipt_op,
    remit_out as remit_out_op,
    swift_in as swift_in_op,
    swift_out as swift_out_op,
    swift_return as swift_return_op,
)
from app.engine.operations.remit_out import BeneficiaryRequiredError
from app.engine.posting import (
    BackdatedEntryRequiresAdminError,
    CreditLimitExceededError,
    InsufficientBalanceError,
    OutageWindowRequiredError,
    OverrideReasonRequiredError,
    UnbalancedEntryError,
)
from app.engine.profit import NegativeMarginReasonRequiredError
from app.config import settings
from app.models import Beneficiary, Client, JournalEntry, JournalLine, User
from app.models.partners import RemitOutDestination
from app.schemas.operations import (
    AdjustmentRequest,
    CashTransferRequest,
    EntryResponse,
    ExchangeChainRequest,
    ExchangeChainResponse,
    ExchangeLotRequest,
    ExchangeRatesRequest,
    ExpenseRequest,
    LocalMoveRequest,
    OpeningRequest,
    PaymentRequest,
    ReceiptRequest,
    RemitOutRequest,
    SwiftInRequest,
    SwiftOutRequest,
    SwiftReturnRequest,
)
from app.security.deps import require_role, verify_csrf
from app.security.permissions import Action, PermissionDeniedError, require_permission

router = APIRouter(prefix="/operations", tags=["operations"], dependencies=[Depends(verify_csrf)])

_ENGINE_ERROR_STATUS: list[tuple[type[Exception], int]] = [
    (BeneficiaryRequiredError, status.HTTP_422_UNPROCESSABLE_ENTITY),
    (NegativeMarginReasonRequiredError, status.HTTP_422_UNPROCESSABLE_ENTITY),
    (OverrideReasonRequiredError, status.HTTP_422_UNPROCESSABLE_ENTITY),
    (InvalidClientLocationError, status.HTTP_422_UNPROCESSABLE_ENTITY),
    (AccountNotFoundError, status.HTTP_404_NOT_FOUND),
    (CreditLimitExceededError, status.HTTP_409_CONFLICT),
    (InsufficientBalanceError, status.HTTP_409_CONFLICT),
    (IdempotencyConflict, status.HTTP_409_CONFLICT),
    (BackdatedEntryRequiresAdminError, status.HTTP_403_FORBIDDEN),
    (OutageWindowRequiredError, status.HTTP_403_FORBIDDEN),
    (UnbalancedEntryError, status.HTTP_500_INTERNAL_SERVER_ERROR),
]


def _run(fn: Callable[[], JournalEntry]) -> JournalEntry:
    try:
        return fn()
    except tuple(cls for cls, _ in _ENGINE_ERROR_STATUS) as exc:
        for cls, code in _ENGINE_ERROR_STATUS:
            if isinstance(exc, cls):
                raise HTTPException(code, str(exc)) from exc
        raise  # pragma: no cover — لا يُصل إليه، كل صنف مُغطّى أعلاه


def _idempotency_key(idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")) -> str:
    if not idempotency_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ترويسة Idempotency-Key إلزامية")
    return idempotency_key


def _get_client(db: OrmSession, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا عميل بالمعرّف {client_id}")
    return client


def _get_beneficiary(db: OrmSession, beneficiary_id: int, *, client_id: int) -> Beneficiary:
    beneficiary = db.get(Beneficiary, beneficiary_id)
    if beneficiary is None or beneficiary.client_id != client_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا مستفيد بالمعرّف {beneficiary_id} لهذا العميل")
    return beneficiary


def _require_override_permission(current_user: User) -> None:
    """§٧-١٣: تجاوز ائتمان/رصيد سالب مدير فقط — يُفحص إضافياً فوق POST_ENTRY
    حين allow_negative=true، بصرف النظر عن كون الدور محاسباً يملك POST_ENTRY."""
    try:
        require_permission(current_user.role, Action.OVERRIDE_CREDIT_OR_BALANCE)
    except PermissionDeniedError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc


def _entry_response(entry: JournalEntry) -> EntryResponse:
    return EntryResponse(
        id=entry.id,
        entry_no=entry.entry_no,
        status=entry.status.value if hasattr(entry.status, "value") else entry.status,
        profit_amount=entry.profit_amount,
        profit_currency=entry.profit_currency,
        chain_ref=entry.chain_ref,
        chain_seq=entry.chain_seq,
        chain_total=entry.chain_total,
    )


@router.post("/receipt", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def create_receipt(
    payload: ReceiptRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
    idempotency_key: str = Depends(_idempotency_key),
) -> EntryResponse:
    client = _get_client(db, payload.client_id)
    now = system_clock()
    entry = _run(lambda: receipt_op.execute(
        db, client=client, currency_code=payload.currency_code, location_code=payload.location_code,
        amount=payload.amount, receiving_account_code=payload.receiving_account_code,
        work_timezone=settings.work_timezone, created_by=current_user.id, now=now,
        idempotency_key=idempotency_key, payment_method=payload.payment_method, description=payload.description,
    ))
    db.commit()
    return _entry_response(entry)


@router.post("/payment", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: PaymentRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
    idempotency_key: str = Depends(_idempotency_key),
) -> EntryResponse:
    if payload.allow_negative:
        _require_override_permission(current_user)
    client = _get_client(db, payload.client_id)
    now = system_clock()
    entry = _run(lambda: payment_op.execute(
        db, client=client, currency_code=payload.currency_code, location_code=payload.location_code,
        amount=payload.amount, paying_account_code=payload.paying_account_code,
        work_timezone=settings.work_timezone, created_by=current_user.id, now=now,
        idempotency_key=idempotency_key, description=payload.description,
        allow_negative=payload.allow_negative, override_reason=payload.override_reason,
    ))
    db.commit()
    return _entry_response(entry)


@router.post("/exchange", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def create_exchange(
    payload: ExchangeRatesRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
    idempotency_key: str = Depends(_idempotency_key),
) -> EntryResponse:
    client = _get_client(db, payload.client_id)
    now = system_clock()
    entry = _run(lambda: exchange_op.execute_via_rates(
        db, client=client, from_currency=payload.from_currency, from_location_code=payload.from_location_code,
        to_currency=payload.to_currency, to_location_code=payload.to_location_code, amount=payload.amount,
        cost_rate=payload.cost_rate, client_rate=payload.client_rate, work_timezone=settings.work_timezone,
        created_by=current_user.id, now=now, idempotency_key=idempotency_key, description=payload.description,
        negative_margin_reason=payload.negative_margin_reason,
    ))
    db.commit()
    return _entry_response(entry)


@router.post("/exchange/from-lot", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def create_exchange_from_lot(
    payload: ExchangeLotRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
    idempotency_key: str = Depends(_idempotency_key),
) -> EntryResponse:
    client = _get_client(db, payload.client_id)
    now = system_clock()
    entry = _run(lambda: exchange_op.execute_via_lot(
        db, client=client, from_location_code=payload.from_location_code, to_location_code=payload.to_location_code,
        amount=payload.amount, client_rate=payload.client_rate, work_timezone=settings.work_timezone,
        created_by=current_user.id, now=now, idempotency_key=idempotency_key, description=payload.description,
    ))
    db.commit()
    return _entry_response(entry)


@router.post("/exchange-chain", response_model=ExchangeChainResponse, status_code=status.HTTP_201_CREATED)
def create_exchange_chain(
    payload: ExchangeChainRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
    idempotency_key: str = Depends(_idempotency_key),
) -> ExchangeChainResponse:
    """§٢-٩: معالج الخطوتين — قيدان `EXCHANGE` منفصلان مربوطان `chain_ref`
    واحد، ذرّياً (كلاهما داخل معاملة `db` نفسها، لا commit جزئي).

    مبلغ الخطوة ٢ **ليس** مُدخلاً مباشراً من الطلب — يُشتق من المبلغ
    الفعلي المُقيَّد فعلاً لحساب العميل في نهاية الخطوة ١ (بعد تقريب
    GIVEN_TO_CLIENT)، فلا يمكن لواجهة أن تُرسل مبلغاً مصطنعاً للخطوة ٢
    يخالف ما رحّلته الخطوة ١ فعلياً.
    """
    client = _get_client(db, payload.client_id)
    now = system_clock()
    step1_holder: dict = {}

    def _step1(chain_ref: str, chain_seq: int, chain_total: int) -> JournalEntry:
        entry = exchange_op.execute_via_rates(
            db, client=client, from_currency=payload.step1.from_currency,
            from_location_code=payload.step1.from_location_code, to_currency=payload.step1.to_currency,
            to_location_code=payload.step1.to_location_code, amount=payload.step1.amount,
            cost_rate=payload.step1.cost_rate, client_rate=payload.step1.client_rate,
            work_timezone=settings.work_timezone, created_by=current_user.id, now=now,
            idempotency_key=f"{idempotency_key}-1", description=payload.description,
            negative_margin_reason=payload.step1.negative_margin_reason,
            chain_ref=chain_ref, chain_seq=chain_seq, chain_total=chain_total,
        )
        step1_holder["entry"] = entry
        return entry

    def _step2(chain_ref: str, chain_seq: int, chain_total: int) -> JournalEntry:
        step1_entry = step1_holder["entry"]
        step2_from_account = get_or_create_client_account(
            db, client=client, currency_code=payload.step1.to_currency, location_code=payload.step1.to_location_code
        )
        credited_line = db.execute(
            select(JournalLine).where(
                JournalLine.entry_id == step1_entry.id,
                JournalLine.account_id == step2_from_account.id,
                JournalLine.credit > 0,
            )
        ).scalar_one()
        return exchange_op.execute_via_rates(
            db, client=client, from_currency=payload.step1.to_currency,
            from_location_code=payload.step1.to_location_code, to_currency=payload.step2.to_currency,
            to_location_code=payload.step2.to_location_code, amount=credited_line.credit,
            cost_rate=payload.step2.cost_rate, client_rate=payload.step2.client_rate,
            work_timezone=settings.work_timezone, created_by=current_user.id, now=now,
            idempotency_key=f"{idempotency_key}-2", description=payload.description,
            negative_margin_reason=payload.step2.negative_margin_reason,
            chain_ref=chain_ref, chain_seq=chain_seq, chain_total=chain_total,
        )

    result = _run(lambda: chain.execute_two_step_chain(
        db, entry_date=_clock.local_entry_date(now, settings.work_timezone), step1=_step1, step2=_step2
    ))
    db.commit()
    return ExchangeChainResponse(
        chain_ref=result.chain_ref,
        step1=_entry_response(result.step1_entry),
        step2=_entry_response(result.step2_entry),
    )


@router.post("/cash-transfer", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def create_cash_transfer(
    payload: CashTransferRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
    idempotency_key: str = Depends(_idempotency_key),
) -> EntryResponse:
    client = _get_client(db, payload.client_id)
    now = system_clock()
    entry = _run(lambda: cash_transfer_op.execute(
        db, client=client, currency_code=payload.currency_code, from_location_code=payload.from_location_code,
        to_location_code=payload.to_location_code, amount=payload.amount,
        source_account_code=payload.source_account_code, execution_account_code=payload.execution_account_code,
        collection_account_code=payload.collection_account_code, commission_currency=payload.commission_currency,
        client_commission_amount=payload.client_commission_amount,
        cost_commission_amount=payload.cost_commission_amount,
        cost_correspondent_account_code=payload.cost_correspondent_account_code,
        work_timezone=settings.work_timezone, created_by=current_user.id, now=now,
        idempotency_key=idempotency_key, description=payload.description,
    ))
    db.commit()
    return _entry_response(entry)


@router.post("/local-move", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def create_local_move(
    payload: LocalMoveRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
    idempotency_key: str = Depends(_idempotency_key),
) -> EntryResponse:
    now = system_clock()
    entry = _run(lambda: local_move_op.execute(
        db, currency_code=payload.currency_code, from_account_code=payload.from_account_code,
        to_account_code=payload.to_account_code, amount=payload.amount, work_timezone=settings.work_timezone,
        created_by=current_user.id, now=now, idempotency_key=idempotency_key, fee_amount=payload.fee_amount,
        description=payload.description,
    ))
    db.commit()
    return _entry_response(entry)


@router.post("/remit-out", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def create_remit_out(
    payload: RemitOutRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
    idempotency_key: str = Depends(_idempotency_key),
) -> EntryResponse:
    client = _get_client(db, payload.client_id)
    beneficiary = _get_beneficiary(db, payload.beneficiary_id, client_id=client.id)
    now = system_clock()
    entry = _run(lambda: remit_out_op.execute(
        db, client=client, from_location_code=payload.from_location_code,
        partner_account_code=payload.partner_account_code, beneficiary=beneficiary,
        beneficiary_amount=payload.beneficiary_amount, cost_rate=payload.cost_rate,
        client_rate=payload.client_rate, work_timezone=settings.work_timezone, created_by=current_user.id,
        now=now, idempotency_key=idempotency_key, purpose=payload.purpose, description=payload.description,
        negative_margin_reason=payload.negative_margin_reason,
    ))
    db.commit()
    response = _entry_response(entry)
    destination = db.execute(
        select(RemitOutDestination).where(RemitOutDestination.entry_id == entry.id)
    ).scalar_one_or_none()
    if destination is not None:
        response.beneficiary_name_snapshot = destination.beneficiary_name_snapshot
        response.account_number_snapshot = destination.account_number_snapshot
        response.bank_name_snapshot = destination.bank_name_snapshot
    return response


@router.post("/swift-out", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def create_swift_out(
    payload: SwiftOutRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
    idempotency_key: str = Depends(_idempotency_key),
) -> EntryResponse:
    now = system_clock()
    entry = _run(lambda: swift_out_op.execute(
        db, partner_account_code=payload.partner_account_code, amount=payload.amount,
        work_timezone=settings.work_timezone, created_by=current_user.id, now=now,
        idempotency_key=idempotency_key, external_ref=payload.external_ref, description=payload.description,
    ))
    db.commit()
    return _entry_response(entry)


@router.post("/swift-in", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def create_swift_in(
    payload: SwiftInRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
    idempotency_key: str = Depends(_idempotency_key),
) -> EntryResponse:
    now = system_clock()
    entry = _run(lambda: swift_in_op.execute(
        db, swift_movement_id=payload.swift_movement_id, total_amount=payload.total_amount,
        fee_amount=payload.fee_amount, receiving_account_code=payload.receiving_account_code,
        work_timezone=settings.work_timezone, created_by=current_user.id, now=now,
        idempotency_key=idempotency_key, bank_conversion_rate=payload.bank_conversion_rate,
        description=payload.description,
    ))
    db.commit()
    return _entry_response(entry)


@router.post("/swift-return", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def create_swift_return(
    payload: SwiftReturnRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
    idempotency_key: str = Depends(_idempotency_key),
) -> EntryResponse:
    client = _get_client(db, payload.client_id)
    now = system_clock()
    entry = _run(lambda: swift_return_op.execute(
        db, swift_movement_id=payload.swift_movement_id, partner_account_code=payload.partner_account_code,
        total_amount=payload.total_amount, client=client, client_location_code=payload.client_location_code,
        return_fee_amount=payload.return_fee_amount, work_timezone=settings.work_timezone,
        created_by=current_user.id, now=now, idempotency_key=idempotency_key, description=payload.description,
    ))
    db.commit()
    return _entry_response(entry)


@router.post("/expense", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
    idempotency_key: str = Depends(_idempotency_key),
) -> EntryResponse:
    if payload.allow_negative:
        _require_override_permission(current_user)
    now = system_clock()
    entry = _run(lambda: expense_op.execute(
        db, expense_account_code=payload.expense_account_code, currency_code=payload.currency_code,
        paying_account_code=payload.paying_account_code, amount=payload.amount, description=payload.description,
        work_timezone=settings.work_timezone, created_by=current_user.id, now=now,
        idempotency_key=idempotency_key, allow_negative=payload.allow_negative,
        override_reason=payload.override_reason,
    ))
    db.commit()
    return _entry_response(entry)


@router.post("/opening", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def create_opening(
    payload: OpeningRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.OPENING_BALANCES)),
    idempotency_key: str = Depends(_idempotency_key),
) -> EntryResponse:
    now = system_clock()
    entry = _run(lambda: opening_op.execute(
        db, account_code=payload.account_code, currency_code=payload.currency_code, amount=payload.amount,
        is_debit=payload.is_debit, as_of_date=payload.as_of_date, source_type=payload.source_type,
        confidence=payload.confidence, approved_by=current_user.id, created_by=current_user.id, now=now,
        idempotency_key=idempotency_key, source_note=payload.source_note,
    ))
    db.commit()
    return _entry_response(entry)


@router.post("/adjustment", response_model=EntryResponse, status_code=status.HTTP_201_CREATED)
def create_adjustment(
    payload: AdjustmentRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.OVERRIDE_CREDIT_OR_BALANCE)),
    idempotency_key: str = Depends(_idempotency_key),
) -> EntryResponse:
    now = system_clock()
    entry = _run(lambda: adjustment_op.execute(
        db, account_code=payload.account_code, currency_code=payload.currency_code, amount=payload.amount,
        is_debit=payload.is_debit, reason=payload.reason, work_timezone=settings.work_timezone,
        created_by=current_user.id, now=now, idempotency_key=idempotency_key,
        allow_negative=payload.allow_negative,
    ))
    db.commit()
    return _entry_response(entry)
