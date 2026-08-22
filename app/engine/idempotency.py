"""§٦-٤ — مفتاح التفرّد: نفس المفتاح بنفس المحتوى يُعيد نفس الرد بلا قيد
جديد، وبنفس المفتاح بمحتوى مختلف يُرفض. الاحتفاظ ٢٤ ساعة يُنظَّف خارج هذا
الملف (مهمة صيانة دورية)، لا يُفرض هنا.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models import IdempotencyKey


class IdempotencyConflict(Exception):
    """نفس مفتاح التفرّد استُخدم بمحتوى مختلف — ٤٠٩ على مستوى الـ API لاحقاً."""


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _hash_payload(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=_default).encode("utf-8")
    ).hexdigest()


@dataclass
class IdempotentResult:
    entry_id: int
    entry_no: str
    replayed: bool  # True إن كان هذا رداً مُعاداً من مفتاح سابق لا قيداً جديداً


def run(
    db: Session, *, idempotency_key: str, request_payload: dict, create_fn: Callable[[], Any]
) -> IdempotentResult:
    """`create_fn` يُنشئ ويُرحّل القيد ويُعيد كائناً له `.id` و`.entry_no`."""
    request_hash = _hash_payload(request_payload)
    existing = db.get(IdempotencyKey, idempotency_key)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflict(
                f"مفتاح التفرّد {idempotency_key} استُخدم من قبل بمحتوى مختلف"
            )
        cached = existing.response_json
        return IdempotentResult(entry_id=cached["entry_id"], entry_no=cached["entry_no"], replayed=True)

    entry = create_fn()
    response = {"entry_id": entry.id, "entry_no": entry.entry_no}
    db.add(
        IdempotencyKey(
            key=idempotency_key,
            request_hash=request_hash,
            response_json=response,
            entry_id=entry.id,
        )
    )
    db.flush()
    return IdempotentResult(entry_id=entry.id, entry_no=entry.entry_no, replayed=False)
