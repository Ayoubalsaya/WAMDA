"""إلغاء · تعديل · تعليقات على قيود — §٥ قاعدة ٢ ("تعديل" = عكس + جديد).

يُغلِّف محرّكات عكس موجودة أصلاً (`posting.reverse_entry` · `chain.reverse_chain`
· `swift_in.reverse` وما أُضيف بجانبها هنا `swift_out.reverse`/`swift_return.reverse`
لنفس السبب: تلك العمليات تمسّ `swift_movements`، وعكسها بالدالة العامة وحدها
يترك تلك الحركات في حالة فاسدة بصمت) — لا منطق محاسبي جديد في هذا الملف.

الإلغاء والتعديل: `Action.EDIT_POSTED_ENTRY` (مدير حصراً). التعليقات:
`Action.POST_ENTRY` (مدير/محاسب) — أي من يملك صلاحية الإدخال يعلّق.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.engine import chain, posting
from app.engine.accounts_repo import AccountNotFoundError, InvalidClientLocationError
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
from app.engine.operations.swift_in import SwiftInAlreadyConsumedError
from app.engine.operations.swift_out import SwiftOutAlreadyProgressedError
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
from app.models import EntryComment, JournalEntry, User
from app.models.enums import EntryStatus, OperationType, SessionSubjectType
from app.routers.operations import _entry_response, _get_client, _run
from app.schemas.operations import (
    AdjustmentRequest,
    CancelRequest,
    CancelResponse,
    CashTransferRequest,
    CommentCreate,
    CommentOut,
    EditRequest,
    EditResponse,
    EntryResponse,
    ExchangeLotRequest,
    ExpenseRequest,
    HistoryResponse,
    HistoryStep,
    LocalMoveRequest,
    OpeningRequest,
    PaymentRequest,
    ReceiptRequest,
    RemitOutRequest,
    SwiftInRequest,
    SwiftOutRequest,
    SwiftReturnRequest,
    ExchangeRatesRequest,
)
from app.security import audit
from app.security.deps import require_role, verify_csrf
from app.security.permissions import Action

router = APIRouter(prefix="/operations", tags=["operations"])

_CLOSED_PERIOD_MESSAGE = "القيد الأصلي في فترة مقفلة — افتح الفترة أولاً من الإعدادات ثم أعد المحاولة"

# كل مُدخل: (نوع الطلب، دالة إنشاء بلا commit) — نسخة طبق الأصل من استدعاء
# المحرّك في كل مسار إنشاء بـ`operations.py`، فقط بلا commit وبلا تغليف
# EntryResponse (نُعيد JournalEntry الخام لربطه بـ`replaces_entry_id` قبل
# commit واحد يشمل العكس والإنشاء معاً — ذرّية حقيقية، لا commit مزدوج).
# EXCHANGE يُعدَّل عبر مخطّط الأسعار العام فقط (لا سلسلة، لا دفعة رمبي
# محدَّدة — كلاهما خارج نطاق "تعديل" هنا، الأولى محظورة أصلاً أدناه
# والثانية تحتاج قراراً منتجياً منفصلاً: أي دفعة تُستهلك بعد التعديل).


def _create_receipt(db: OrmSession, op: ReceiptRequest, user: User, now: datetime, idem: str) -> JournalEntry:
    client = _get_client(db, op.client_id)
    entry = _run(lambda: receipt_op.execute(
        db, client=client, currency_code=op.currency_code, location_code=op.location_code,
        amount=op.amount, receiving_account_code=op.receiving_account_code,
        work_timezone=settings.work_timezone, created_by=user.id, now=now,
        idempotency_key=idem, payment_method=op.payment_method, description=op.description,
    ))
    entry.note = op.note
    return entry


def _create_payment(db: OrmSession, op: PaymentRequest, user: User, now: datetime, idem: str) -> JournalEntry:
    client = _get_client(db, op.client_id)
    entry = _run(lambda: payment_op.execute(
        db, client=client, currency_code=op.currency_code, location_code=op.location_code,
        amount=op.amount, paying_account_code=op.paying_account_code,
        work_timezone=settings.work_timezone, created_by=user.id, now=now,
        idempotency_key=idem, description=op.description,
        allow_negative=op.allow_negative, override_reason=op.override_reason,
    ))
    entry.note = op.note
    return entry


def _create_exchange(db: OrmSession, op: ExchangeRatesRequest, user: User, now: datetime, idem: str) -> JournalEntry:
    client = _get_client(db, op.client_id) if op.client_id is not None else None
    entry = _run(lambda: exchange_op.execute_via_rates(
        db, client=client, from_currency=op.from_currency, from_location_code=op.from_location_code,
        to_currency=op.to_currency, to_location_code=op.to_location_code, amount=op.amount,
        source_account_code=op.source_account_code, destination_account_code=op.destination_account_code,
        cost_rate=op.cost_rate, client_rate=op.client_rate, work_timezone=settings.work_timezone,
        created_by=user.id, now=now, idempotency_key=idem, description=op.description,
        negative_margin_reason=op.negative_margin_reason,
    ))
    entry.note = op.note
    return entry


def _create_cash_transfer(db: OrmSession, op: CashTransferRequest, user: User, now: datetime, idem: str) -> JournalEntry:
    client = _get_client(db, op.client_id)
    entry = _run(lambda: cash_transfer_op.execute(
        db, client=client, currency_code=op.currency_code, from_location_code=op.from_location_code,
        to_location_code=op.to_location_code, amount=op.amount,
        source_account_code=op.source_account_code, execution_account_code=op.execution_account_code,
        collection_account_code=op.collection_account_code, commission_currency=op.commission_currency,
        client_commission_amount=op.client_commission_amount,
        cost_commission_amount=op.cost_commission_amount,
        cost_correspondent_account_code=op.cost_correspondent_account_code,
        work_timezone=settings.work_timezone, created_by=user.id, now=now,
        idempotency_key=idem, description=op.description,
        allow_negative=op.allow_negative, override_reason=op.override_reason,
    ))
    entry.note = op.note
    return entry


def _create_local_move(db: OrmSession, op: LocalMoveRequest, user: User, now: datetime, idem: str) -> JournalEntry:
    entry = _run(lambda: local_move_op.execute(
        db, currency_code=op.currency_code, from_account_code=op.from_account_code,
        to_account_code=op.to_account_code, amount=op.amount, work_timezone=settings.work_timezone,
        created_by=user.id, now=now, idempotency_key=idem, fee_amount=op.fee_amount,
        description=op.description,
        allow_negative=op.allow_negative, override_reason=op.override_reason,
    ))
    entry.note = op.note
    return entry


def _create_remit_out(db: OrmSession, op: RemitOutRequest, user: User, now: datetime, idem: str) -> JournalEntry:
    client = _get_client(db, op.client_id)
    entry = _run(lambda: remit_out_op.execute(
        db, client=client, from_location_code=op.from_location_code,
        partner_account_code=op.partner_account_code, currency_code=op.currency_code,
        amount=op.amount, cost_rate=op.cost_rate,
        client_rate=op.client_rate, work_timezone=settings.work_timezone, created_by=user.id,
        now=now, idempotency_key=idem, description=op.description,
        negative_margin_reason=op.negative_margin_reason,
        allow_negative=op.allow_negative, override_reason=op.override_reason,
    ))
    entry.note = op.note
    return entry


def _create_swift_out(db: OrmSession, op: SwiftOutRequest, user: User, now: datetime, idem: str) -> JournalEntry:
    entry = _run(lambda: swift_out_op.execute(
        db, partner_account_code=op.partner_account_code, amount=op.amount,
        work_timezone=settings.work_timezone, created_by=user.id, now=now,
        idempotency_key=idem, external_ref=op.external_ref, description=op.description,
        allow_negative=op.allow_negative, override_reason=op.override_reason,
    ))
    entry.note = op.note
    return entry


def _create_swift_in(db: OrmSession, op: SwiftInRequest, user: User, now: datetime, idem: str) -> JournalEntry:
    entry = _run(lambda: swift_in_op.execute(
        db, swift_movement_id=op.swift_movement_id, total_amount=op.total_amount,
        fee_amount=op.fee_amount, receiving_account_code=op.receiving_account_code,
        work_timezone=settings.work_timezone, created_by=user.id, now=now,
        idempotency_key=idem, bank_conversion_rate=op.bank_conversion_rate,
        description=op.description,
    ))
    entry.note = op.note
    return entry


def _create_swift_return(db: OrmSession, op: SwiftReturnRequest, user: User, now: datetime, idem: str) -> JournalEntry:
    client = _get_client(db, op.client_id)
    entry = _run(lambda: swift_return_op.execute(
        db, swift_movement_id=op.swift_movement_id, partner_account_code=op.partner_account_code,
        total_amount=op.total_amount, client=client, client_location_code=op.client_location_code,
        return_fee_amount=op.return_fee_amount, work_timezone=settings.work_timezone,
        created_by=user.id, now=now, idempotency_key=idem, description=op.description,
    ))
    entry.note = op.note
    return entry


def _create_expense(db: OrmSession, op: ExpenseRequest, user: User, now: datetime, idem: str) -> JournalEntry:
    entry = _run(lambda: expense_op.execute(
        db, expense_account_code=op.expense_account_code, currency_code=op.currency_code,
        paying_account_code=op.paying_account_code, amount=op.amount, description=op.description,
        work_timezone=settings.work_timezone, created_by=user.id, now=now,
        idempotency_key=idem, allow_negative=op.allow_negative,
        override_reason=op.override_reason,
    ))
    entry.note = op.note
    return entry


def _create_opening(db: OrmSession, op: OpeningRequest, user: User, now: datetime, idem: str) -> JournalEntry:
    from app.engine.accounts_repo import get_or_create_client_account
    if op.client_id is not None:
        client = _get_client(db, op.client_id)
        target_code = get_or_create_client_account(
            db, client=client, currency_code=op.currency_code, location_code=op.location_code,
        ).code
    else:
        target_code = op.account_code
    entry = _run(lambda: opening_op.execute(
        db, account_code=target_code, currency_code=op.currency_code, amount=op.amount,
        is_debit=op.is_debit, as_of_date=op.as_of_date, source_type=op.source_type,
        confidence=op.confidence, approved_by=user.id, created_by=user.id, now=now,
        idempotency_key=idem, source_note=op.source_note,
    ))
    entry.note = op.note
    return entry


def _create_adjustment(db: OrmSession, op: AdjustmentRequest, user: User, now: datetime, idem: str) -> JournalEntry:
    entry = _run(lambda: adjustment_op.execute(
        db, account_code=op.account_code, currency_code=op.currency_code, amount=op.amount,
        is_debit=op.is_debit, reason=op.reason, work_timezone=settings.work_timezone,
        created_by=user.id, now=now, idempotency_key=idem,
        allow_negative=op.allow_negative,
    ))
    entry.note = op.note
    return entry


_CREATE_DISPATCH: dict[OperationType, tuple[type[BaseModel], Callable]] = {
    OperationType.RECEIPT: (ReceiptRequest, _create_receipt),
    OperationType.PAYMENT: (PaymentRequest, _create_payment),
    OperationType.EXCHANGE: (ExchangeRatesRequest, _create_exchange),
    OperationType.CASH_TRANSFER: (CashTransferRequest, _create_cash_transfer),
    OperationType.LOCAL_MOVE: (LocalMoveRequest, _create_local_move),
    OperationType.REMIT_OUT: (RemitOutRequest, _create_remit_out),
    OperationType.SWIFT_OUT: (SwiftOutRequest, _create_swift_out),
    OperationType.SWIFT_IN: (SwiftInRequest, _create_swift_in),
    OperationType.SWIFT_RETURN: (SwiftReturnRequest, _create_swift_return),
    OperationType.EXPENSE: (ExpenseRequest, _create_expense),
    OperationType.OPENING: (OpeningRequest, _create_opening),
    OperationType.ADJUSTMENT: (AdjustmentRequest, _create_adjustment),
}


def _create_exchange_lot(db: OrmSession, op: ExchangeLotRequest, user: User, now: datetime, idem: str) -> JournalEntry:
    """بيع رمبي من مخزون السويفت (FIFO تلقائي، بلا cost_rate) — للتعديل: يُستدعى بعد عكس الأصل في
    المعاملة نفسها فيستهلك الجديد من دفعات أُعيدت كمياتها لتوّها."""
    client = _get_client(db, op.client_id)
    entry = _run(lambda: exchange_op.execute_via_lot(
        db, client=client, from_location_code=op.from_location_code, to_location_code=op.to_location_code,
        amount=op.amount, client_rate=op.client_rate, work_timezone=settings.work_timezone,
        created_by=user.id, now=now, idempotency_key=idem, description=op.description,
    ))
    entry.note = op.note
    return entry


def _dispatch_for(entry: JournalEntry):
    """نوع الطلب ودالة الإنشاء لتعديل `entry`. EXCHANGE بلا `cost_rate` وبعميل = بيع رمبي من دفعة
    (`execute_via_lot` يترك cost_rate فارغاً) — مخطّطه `ExchangeLotRequest` لا مخطّط الأسعار."""
    if entry.operation_type == OperationType.EXCHANGE and entry.cost_rate is None and entry.client_id is not None:
        return ExchangeLotRequest, _create_exchange_lot
    return _CREATE_DISPATCH.get(entry.operation_type)


def _get_entry(db: OrmSession, entry_id: int) -> JournalEntry:
    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا قيد بالمعرّف {entry_id}")
    return entry


def _reject_reversal_entry(entry: JournalEntry) -> None:
    """قيد عكسي (ناتج عن إلغاء/تعديل) لا يُلغى ولا يُعدَّل: عكسه كان سيُعيد أثر القيد الأصلي في الحسابات
    دون إعادة استهلاكه من الدفعة — مخزون رمبي يتباين بصمت. المسار الصحيح: أدخل عملية جديدة."""
    if entry.reverses_entry_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"القيد {entry.entry_no} قيد عكسي ناتج عن إلغاء/تعديل — لا يُلغى ولا يُعدَّل؛ أدخل عملية جديدة بدلاً منه",
        )


def _reverse_one(db: OrmSession, entry: JournalEntry, *, reason: str, created_by: int, now) -> JournalEntry:
    """يوجّه لنسخة `reverse` الخاصة بنوع العملية إن وُجدت (السويفت الثلاثة
    — تمسّ `swift_movements`)، وإلا العامة `posting.reverse_entry`."""
    if entry.operation_type == OperationType.SWIFT_IN:
        return swift_in_op.reverse(db, entry=entry, reason=reason, created_by=created_by, now=now)
    if entry.operation_type == OperationType.SWIFT_OUT:
        return swift_out_op.reverse(db, entry=entry, reason=reason, created_by=created_by, now=now)
    if entry.operation_type == OperationType.SWIFT_RETURN:
        return swift_return_op.reverse(db, entry=entry, reason=reason, created_by=created_by, now=now)
    return posting.reverse_entry(db, entry, reason=reason, created_by=created_by, now=now)


def _run_reversal(fn: Callable[[], object]):
    """مثل `_run` في operations.py لكن بأخطاء عكس القيد تحديداً — رسالة
    واضحة للفترة المقفلة بدل رسالة "سبب إلزامي" المضلِّلة هنا تحديداً
    (`reverse_entry` لا يمرّر backdate_reason فيرث نفس بوابة الفترة
    المقفلة من `create_draft_entry` بلا قصد صريح — نستغل هذا الرفض
    الطبيعي كحارس، فقط بصياغة صحيحة)."""
    try:
        return fn()
    except (OverrideReasonRequiredError, BackdatedEntryRequiresAdminError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _CLOSED_PERIOD_MESSAGE) from exc
    except SwiftInAlreadyConsumedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except SwiftOutAlreadyProgressedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (CreditLimitExceededError, InsufficientBalanceError) as exc:
        # ٢٠٢٦-١٠-٠٢: وكذلك رصيد حساب الشركة (صندوق/بنك) السالب — على قاعدة نظيفة يكون الصندوق
        # صفراً فيصير عكس قبض مُنفَق سالباً (كان 500 خاماً لأن قاعدة التطوير القديمة تخفي ذلك).
        # ٢٠٢٦-٠٩-٢٥ (اكتُشف أثناء تحقق حي لصرافة الخزينة): عكس قيد بترتيب
        # غير LIFO قد يدفع رصيداً سالباً فيفشل بهذا الخطأ تماماً كأي قيد
        # جديد — كان يُترك بلا معالجة هنا فيصل 500 خاماً بدل 409 واضح.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except UnbalancedEntryError as exc:  # pragma: no cover — خط دفاع أخير، لا يُتوقَّع بلوغه
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc


@router.post("/{entry_id}/cancel", response_model=CancelResponse, dependencies=[Depends(verify_csrf)])
def cancel_entry(
    entry_id: int,
    payload: CancelRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.EDIT_POSTED_ENTRY)),
) -> CancelResponse:
    entry = _get_entry(db, entry_id)
    if entry.status != EntryStatus.POSTED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"القيد بحالة {entry.status.value} — لا يمكن إلغاؤه")
    _reject_reversal_entry(entry)
    reason = payload.reason
    now = system_clock()

    if entry.chain_ref:
        chain_ref = entry.chain_ref
        reversed_entries = _run_reversal(lambda: chain.reverse_chain(
            db, chain_ref=chain_ref, reason=reason, created_by=current_user.id, now=now
        ))
        affected_ids = [e.reverses_entry_id for e in reversed_entries]
    else:
        _run_reversal(lambda: _reverse_one(db, entry, reason=reason, created_by=current_user.id, now=now))
        affected_ids = [entry.id]

    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=current_user.id, action="ENTRY_CANCELLED",
        entity="journal_entries", entity_id=entry.id,
        before={"status": "POSTED"}, after={"status": "REVERSED", "reason": reason, "chain_cascade": bool(entry.chain_ref)},
    )
    db.commit()
    return CancelResponse(cancelled_entry_ids=affected_ids, chain_cascade=bool(entry.chain_ref))


@router.post("/{entry_id}/edit", response_model=EditResponse, dependencies=[Depends(verify_csrf)])
def edit_entry(
    entry_id: int,
    payload: EditRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.EDIT_POSTED_ENTRY)),
) -> EditResponse:
    """§٥ قاعدة ٢: تعديل = عكس الأصل + إنشاء بديل بقيم جديدة، ذرّياً —
    كلاهما في نفس معاملة `db` (لا commit إلا في نهاية هذه الدالة، تماماً
    كمعالج الخطوتين في chain.py). يفشل أحدهما فيتراجع كلاهما معاً —
    `get_db` يُغلق الجلسة بلا commit فترتدّ المعاملة تلقائياً."""
    entry = _get_entry(db, entry_id)
    if entry.status != EntryStatus.POSTED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"القيد بحالة {entry.status.value} — لا يمكن تعديله")
    _reject_reversal_entry(entry)
    if entry.chain_ref:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "عملية ضمن سلسلة (معالج الخطوتين) لا تُعدَّل مباشرة — ألغِ السلسلة كاملة وأعد إدخالها من جديد",
        )
    dispatch = _dispatch_for(entry)
    if dispatch is None:  # pragma: no cover — كل الأنواع الاثنتي عشرة مُغطاة في _CREATE_DISPATCH
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"لا دعم لتعديل عمليات {entry.operation_type.value}")
    schema_cls, create_fn = dispatch
    try:
        parsed_operation = schema_cls(**payload.operation)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    now = system_clock()
    original_entry_no = entry.entry_no
    _run_reversal(lambda: _reverse_one(db, entry, reason=payload.reason, created_by=current_user.id, now=now))
    new_entry = create_fn(db, parsed_operation, current_user, now, f"edit-{uuid4()}")
    new_entry.replaces_entry_id = entry.id

    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=current_user.id, action="ENTRY_EDITED",
        entity="journal_entries", entity_id=entry.id,
        before={"status": "POSTED", "entry_no": original_entry_no},
        after={"status": "REVERSED", "replaced_by": new_entry.entry_no, "reason": payload.reason},
    )
    db.commit()
    return EditResponse(reversed_entry_id=entry.id, new_entry=_entry_response(new_entry))


@router.get("/{entry_id}/comments", response_model=list[CommentOut])
def list_comments(
    entry_id: int,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
) -> list[CommentOut]:
    _get_entry(db, entry_id)
    rows = db.execute(
        select(EntryComment).where(EntryComment.entry_id == entry_id).order_by(EntryComment.created_at)
    ).scalars().all()
    authors = {u.id: u for u in db.execute(select(User).where(User.id.in_({r.created_by for r in rows}))).scalars().all()} if rows else {}
    return [
        CommentOut(
            id=r.id, entry_id=r.entry_id, body=r.body, created_by=r.created_by,
            created_by_name=authors[r.created_by].full_name if r.created_by in authors else "—",
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/{entry_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_csrf)])
def add_comment(
    entry_id: int,
    payload: CommentCreate,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
) -> CommentOut:
    entry = _get_entry(db, entry_id)
    comment = EntryComment(entry_id=entry.id, body=payload.body, created_by=current_user.id)
    db.add(comment)
    db.flush()
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=current_user.id, action="ENTRY_COMMENT_ADDED",
        entity="entry_comments", entity_id=comment.id, after={"entry_id": entry.id, "body": payload.body},
    )
    db.commit()
    return CommentOut(
        id=comment.id, entry_id=comment.entry_id, body=comment.body, created_by=comment.created_by,
        created_by_name=current_user.full_name, created_at=comment.created_at,
    )


@router.get("/{entry_id}/history", response_model=HistoryResponse)
def entry_history(
    entry_id: int,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.POST_ENTRY)),
) -> HistoryResponse:
    """يبني سلسلة تعديل/إلغاء كاملة انطلاقاً من أي قيد فيها — يمشي عبر
    `replaces_entry_id` (تعديلات سابقة) و`reverses_entry_id`/`reversed_by_entry_id`
    (كل إلغاء وعكسه) حتى لا تبقى إشارة جديدة، فيغطي أي عمق تعديلات متتالية."""
    _get_entry(db, entry_id)
    ids: set[int] = {entry_id}
    frontier = [entry_id]
    while frontier:
        rows = db.execute(
            select(JournalEntry).where(JournalEntry.id.in_(frontier))
        ).scalars().all()
        next_frontier: list[int] = []
        for r in rows:
            for related in (r.replaces_entry_id, r.reverses_entry_id, r.reversed_by_entry_id):
                if related is not None and related not in ids:
                    ids.add(related)
                    next_frontier.append(related)
            # القيد البديل الذي حلّ محلّ هذا (إن وُجد) — الاتجاه المعاكس لـreplaces_entry_id
            replaced_by = db.execute(
                select(JournalEntry.id).where(JournalEntry.replaces_entry_id == r.id)
            ).scalar_one_or_none()
            if replaced_by is not None and replaced_by not in ids:
                ids.add(replaced_by)
                next_frontier.append(replaced_by)
        frontier = next_frontier

    all_entries = db.execute(select(JournalEntry).where(JournalEntry.id.in_(ids)).order_by(JournalEntry.id)).scalars().all()
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_({e.created_by for e in all_entries}))).scalars().all()}

    steps = []
    for e in all_entries:
        if e.reverses_entry_id is not None:
            kind = "reversal"
        elif e.replaces_entry_id is not None:
            kind = "replacement"
        else:
            kind = "original"
        steps.append(HistoryStep(
            entry_id=e.id, entry_no=e.entry_no, kind=kind, status=e.status.value,
            created_by_name=users[e.created_by].full_name if e.created_by in users else "—",
            created_at=e.created_at, reason=e.correction_reason,
        ))
    return HistoryResponse(steps=steps)
