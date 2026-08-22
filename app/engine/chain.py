"""§٢-٩ — معالج الخطوتين: `LYD → USD → CNY`. قيدان منفصلان بربحين منفصلين
لا يُدمجان أبداً، مربوطان بـ`chain_ref` واحد **ذرّياً** — كلاهما داخل نفس
معاملة قاعدة البيانات، ينجحان معاً أو يفشلان معاً (لا commit جزئي هنا).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import numbering, posting
from app.models import JournalEntry
from app.models.enums import EntryStatus

StepFn = Callable[[str, int, int], JournalEntry]  # (chain_ref, chain_seq, chain_total) -> JournalEntry


@dataclass
class ChainResult:
    chain_ref: str
    step1_entry: JournalEntry
    step2_entry: JournalEntry


def execute_two_step_chain(db: Session, *, entry_date: date, step1: StepFn, step2: StepFn) -> ChainResult:
    """`step1`/`step2` كل منهما يبني وينشئ ويُرحّل قيد `EXCHANGE` واحداً عبر
    وحدات `operations/`. لا سعر مشترك ولا ربح مدمج — مجرد رابط تتبّع.
    """
    chain_ref = numbering.next_chain_ref(db, entry_date.year)
    step1_entry = step1(chain_ref, 1, 2)
    step2_entry = step2(chain_ref, 2, 2)
    return ChainResult(chain_ref=chain_ref, step1_entry=step1_entry, step2_entry=step2_entry)


def reverse_chain(db: Session, *, chain_ref: str, reason: str, created_by: int, now: datetime) -> list[JournalEntry]:
    """§٢-٩: عكس أي خطوة يفرض عكس السلسلة كاملة — لا نصف سلسلة معكوسة أبداً."""
    entries = db.execute(
        select(JournalEntry)
        .where(JournalEntry.chain_ref == chain_ref, JournalEntry.status == EntryStatus.POSTED)
        .order_by(JournalEntry.chain_seq)
    ).scalars().all()
    if not entries:
        raise ValueError(f"لا قيود مُرحّلة بمرجع سلسلة {chain_ref} لعكسها")
    return [
        posting.reverse_entry(db, entry, reason=reason, created_by=created_by, now=now) for entry in entries
    ]
