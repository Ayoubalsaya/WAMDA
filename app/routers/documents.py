"""مسارات توليد المستندات (§٨) — PDF (Playwright/Chromium `page.pdf()`) و
PNG (`page.screenshot()`)، نفس القالب لكل مقاس مخرَج (`doc_size` هو الفرق
الوحيد). كل مسار يتطلب جلسة موظف صالحة (`require_password_changed`) —
هذه أداة موظف يطبع بها للعميل، ليست بوابة العميل نفسها.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session as OrmSession

from app.config import settings
from app.database import get_db
from app.documents import balance_card as balance_card_doc
from app.documents import receipt as receipt_doc
from app.documents import reports_doc
from app.documents import statement as statement_doc
from app.documents.jinja import render_template
from app.documents.qr import qr_data_uri
from app.documents.render import render_pdf, render_png
from app.documents.xlsx import XLSX_MEDIA_TYPE, report_to_xlsx, statement_to_xlsx
from app.engine.clock import system_clock
from app.public_url import require_public_base_url
from app.security.deps import require_password_changed, require_role
from app.security.permissions import Action

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(require_password_changed)])

_REPORT_BUILDERS = {
    "trial-balance": reports_doc.build_trial_balance_context,
    "founding-reconciliation": reports_doc.build_founding_reconciliation_context,
    "balance-overrides": reports_doc.build_balance_overrides_context,
    "emergency-entries": reports_doc.build_emergency_entries_context,
    "monthly-profit": reports_doc.build_monthly_profit_context,
    "lot-profitability": reports_doc.build_lot_profitability_context,
    "liquidity-position": reports_doc.build_liquidity_position_context,
    "correspondent-balances": reports_doc.build_correspondent_balances_context,
    "boxes-balances": reports_doc.build_boxes_balances_context,
    "debtors": reports_doc.build_debtors_context,
}

# §٨ — التقارير التي تنص الوثيقة على صيغة Excel لها (جدول §٨ حرفياً:
# تجاوزات الرصيد/قيود الطوارئ "PDF" فقط · بطاقة أرصدة المراسلين "PNG·PDF"
# · كشف أرصدة الصناديق "PDF·Excel").
_EXCEL_REPORT_KEYS = frozenset({
    "trial-balance", "founding-reconciliation", "monthly-profit",
    "lot-profitability", "liquidity-position", "boxes-balances", "debtors",
})


def _verify_qr(base_url: str, entry_no: str) -> str:
    """رابط تحقق يفتح بحث الموظف الذكي (المرحلة ٩) على رقم القيد نفسه —
    لا نقطة نهاية تحقق عامة منفصلة (تحتاج تصميم أمان خاص بها، خارج نطاق
    هذه المرحلة)؛ الفحص الحقيقي هنا: مسح الرمز يفتح نتيجة بحث تطابق القيد
    فعلاً، لا صورة زخرفية."""
    return f"{base_url}/?q={entry_no}"


@router.get("/receipt/{entry_id}.pdf")
def receipt_pdf(
    entry_id: int, size: str = Query(default="a4", pattern="^(a4|thermal)$"), db: OrmSession = Depends(get_db),
    base_url: str = Depends(require_public_base_url),
) -> Response:
    now = system_clock()
    ctx = receipt_doc.build_receipt_context(db, entry_id=entry_id, doc_size=size, now=now, work_timezone=settings.work_timezone)
    ctx["qr_data_uri"] = qr_data_uri(_verify_qr(base_url, ctx["doc_subtitle"].split(" — ")[0]))
    html = render_template("receipt.html", **ctx)
    pdf_bytes = render_pdf(html)
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.get("/receipt/{entry_id}.png")
def receipt_png(
    entry_id: int, db: OrmSession = Depends(get_db), base_url: str = Depends(require_public_base_url),
) -> Response:
    now = system_clock()
    ctx = receipt_doc.build_receipt_context(db, entry_id=entry_id, doc_size="png", now=now, work_timezone=settings.work_timezone)
    ctx["qr_data_uri"] = qr_data_uri(_verify_qr(base_url, ctx["doc_subtitle"].split(" — ")[0]))
    html = render_template("receipt.html", **ctx)
    png_bytes = render_png(html, width=720)
    return Response(content=png_bytes, media_type="image/png")


def _balance_card_html(db: OrmSession, client_id: int, base_url: str, *, for_pdf: bool = False):
    now = system_clock()
    ctx = balance_card_doc.build_balance_card_context(db, client_id=client_id, now=now, work_timezone=settings.work_timezone)
    ctx["qr_data_uri"] = qr_data_uri(f"{base_url}/portal")
    ctx["for_pdf"] = for_pdf
    return render_template("balance_card.html", **ctx)


@router.get("/balance-card/{client_id}.png", dependencies=[Depends(require_role(Action.POST_ENTRY))])
def balance_card_png(
    client_id: int, db: OrmSession = Depends(get_db), base_url: str = Depends(require_public_base_url),
) -> Response:
    # §٩ المرحلة ١٢: بطاقة رصيد عميل (تُشارَك عبر واتساب) — نفس حاجز
    # POST_ENTRY لبقية بيانات العميل المالية
    png_bytes = render_png(
        _balance_card_html(db, client_id, base_url),
        width=balance_card_doc.WHATSAPP_CARD_SIZE, height=balance_card_doc.WHATSAPP_CARD_SIZE,
    )
    return Response(content=png_bytes, media_type="image/png")


@router.get("/balance-card/{client_id}.pdf", dependencies=[Depends(require_role(Action.POST_ENTRY))])
def balance_card_pdf(
    client_id: int, db: OrmSession = Depends(get_db), base_url: str = Depends(require_public_base_url),
) -> Response:
    """§٨: بطاقة رصيد عميل — صيغة PDF بجانب PNG (نفس القالب)."""
    pdf_bytes = render_pdf(_balance_card_html(db, client_id, base_url, for_pdf=True))
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.get("/statement/client/{client_id}.pdf", dependencies=[Depends(require_role(Action.POST_ENTRY))])
def client_statement_pdf(
    client_id: int, currency: str, location: str,
    date_from: Optional[date] = None, date_to: Optional[date] = None,
    size: str = Query(default="a4", pattern="^(a4|thermal)$"), db: OrmSession = Depends(get_db),
) -> Response:
    now = system_clock()
    ctx = statement_doc.build_client_statement_context(
        db, client_id=client_id, currency=currency, location=location, doc_size=size,
        date_from=date_from, date_to=date_to, now=now, work_timezone=settings.work_timezone,
    )
    html = render_template("statement.html", **ctx)
    pdf_bytes = render_pdf(html)
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.get(
    "/statement/client/{client_id}.xlsx", dependencies=[Depends(require_role(Action.POST_ENTRY))],
)
def client_statement_xlsx(
    client_id: int, currency: str, location: str,
    date_from: Optional[date] = None, date_to: Optional[date] = None, db: OrmSession = Depends(get_db),
) -> Response:
    """§٨: كشف حساب عميل — Excel (نفس دالة السياق التي تُغذّي PDF)."""
    ctx = statement_doc.build_client_statement_context(
        db, client_id=client_id, currency=currency, location=location, doc_size="a4",
        date_from=date_from, date_to=date_to, now=system_clock(), work_timezone=settings.work_timezone,
    )
    return Response(content=statement_to_xlsx(ctx), media_type=XLSX_MEDIA_TYPE)


@router.get("/statement/account/{account_code}.pdf")
def account_statement_pdf(
    account_code: str, date_from: Optional[date] = None, date_to: Optional[date] = None,
    size: str = Query(default="a4", pattern="^(a4|thermal)$"), db: OrmSession = Depends(get_db),
) -> Response:
    now = system_clock()
    ctx = statement_doc.build_account_statement_context(
        db, account_code=account_code, doc_size=size, date_from=date_from, date_to=date_to,
        now=now, work_timezone=settings.work_timezone,
    )
    html = render_template("statement.html", **ctx)
    pdf_bytes = render_pdf(html)
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.get("/statement/account/{account_code}.xlsx")
def account_statement_xlsx(
    account_code: str, date_from: Optional[date] = None, date_to: Optional[date] = None,
    db: OrmSession = Depends(get_db),
) -> Response:
    """§٨: كشف حساب أساسي (داخلي) — Excel."""
    ctx = statement_doc.build_account_statement_context(
        db, account_code=account_code, doc_size="a4", date_from=date_from, date_to=date_to,
        now=system_clock(), work_timezone=settings.work_timezone,
    )
    return Response(content=statement_to_xlsx(ctx), media_type=XLSX_MEDIA_TYPE)


@router.get("/chain-summary/{chain_ref}.pdf")
def chain_summary_pdf(
    chain_ref: str, size: str = Query(default="a4", pattern="^(a4|thermal)$"), db: OrmSession = Depends(get_db),
) -> Response:
    now = system_clock()
    ctx = reports_doc.build_chain_summary_context(
        db, chain_ref=chain_ref, doc_size=size, now=now, work_timezone=settings.work_timezone,
    )
    html = render_template("report_table.html", **ctx)
    pdf_bytes = render_pdf(html)
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.get("/chain-summary/{chain_ref}.png")
def chain_summary_png(chain_ref: str, db: OrmSession = Depends(get_db)) -> Response:
    """§٨: ملخص سلسلة CHN — صيغة PNG بجانب PDF."""
    ctx = reports_doc.build_chain_summary_context(
        db, chain_ref=chain_ref, doc_size="png", now=system_clock(), work_timezone=settings.work_timezone,
    )
    png_bytes = render_png(render_template("report_table.html", **ctx), width=900)
    return Response(content=png_bytes, media_type="image/png")


def _report_builder_or_404(report_key: str):
    builder = _REPORT_BUILDERS.get(report_key)
    if builder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا تقرير بالاسم {report_key}")
    return builder


@router.get("/reports/{report_key}.pdf")
def report_pdf(
    report_key: str, size: str = Query(default="a4", pattern="^(a4|thermal)$"), db: OrmSession = Depends(get_db),
) -> Response:
    builder = _report_builder_or_404(report_key)
    now = system_clock()
    ctx = builder(db, doc_size=size, now=now, work_timezone=settings.work_timezone)
    html = render_template("report_table.html", **ctx)
    pdf_bytes = render_pdf(html)
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.get("/reports/{report_key}.png")
def report_png(report_key: str, db: OrmSession = Depends(get_db)) -> Response:
    builder = _report_builder_or_404(report_key)
    now = system_clock()
    ctx = builder(db, doc_size="png", now=now, work_timezone=settings.work_timezone)
    html = render_template("report_table.html", **ctx)
    png_bytes = render_png(html, width=900)
    return Response(content=png_bytes, media_type="image/png")


@router.get("/reports/{report_key}.xlsx")
def report_xlsx(report_key: str, db: OrmSession = Depends(get_db)) -> Response:
    """§٨: تصدير Excel للتقارير التي تنص الوثيقة على ذلك (`_EXCEL_REPORT_KEYS`)."""
    if report_key not in _EXCEL_REPORT_KEYS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا صيغة Excel للتقرير {report_key}")
    builder = _report_builder_or_404(report_key)
    ctx = builder(db, doc_size="a4", now=system_clock(), work_timezone=settings.work_timezone)
    return Response(content=report_to_xlsx(ctx), media_type=XLSX_MEDIA_TYPE)
