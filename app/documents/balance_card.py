"""بطاقة رصيد عميل — PNG بمقاس واتساب (١٠٨٠×١٠٨٠، مربّعة تُعرض كاملة في
أي محادثة/حالة واتساب بلا قصّ) + QR يفتح بوابة العميل مباشرة (§٨). لا
cost_rate هنا أصلاً (لا تُقرأ من `JournalEntry` إطلاقاً) — بطاقة أرصدة
فقط، لا تفاصيل عمليات.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as OrmSession

from app.documents.common import base_context
from app.documents.formatting import currency_decimals_map, format_amount
from app.models import Client
from app.routers.clients import _client_balances

WHATSAPP_CARD_SIZE = 1080


def build_balance_card_context(db: OrmSession, *, client_id: int, now: datetime, work_timezone: str) -> dict:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا عميل بالمعرّف {client_id}")

    dec = currency_decimals_map(db)
    balances = _client_balances(db, client_id)
    by_currency: dict[str, list[dict]] = {}
    for b in balances:
        if b.balance == 0:
            continue
        by_currency.setdefault(b.currency_code, []).append({
            "location_code": b.location_code, "amount": format_amount(b.balance, b.currency_code, dec),
        })

    ctx = base_context(db, now=now, work_timezone=work_timezone)
    ctx.update({
        "doc_size": "png", "png_width": WHATSAPP_CARD_SIZE,
        "doc_title": "بطاقة رصيد", "doc_subtitle": None, "qr_data_uri": None,
        "client_name": client.name_ar, "client_code": client.code,
        "groups": [{"currency_code": ccy, "rows": rows} for ccy, rows in sorted(by_currency.items())],
        "show_signatures": False,
    })
    return ctx
