"""توليد PDF/PNG على السيرفر عبر Playwright/Chromium — بديل WeasyPrint
المرفوض (يحتاج GTK3/Pango على مستوى نظام التشغيل، فشل فعلياً على ويندوز
بعدم توافق بنية 32/64-بت، ولا ضمان أبسط على خادم النشر). Playwright
مثبَّت أصلاً منذ المرحلة ٥ (تحقّق Playwright الحيّ)، بلا أي اعتماد نظام
إضافي على أي منصة — ونتيجته مطابقة لما يظهر في المتصفح تماماً لأنه نفس
محرك العرض بالضبط، لا محاكاة CSS منفصلة كما في WeasyPrint.

**متصفح واحد يُعاد استخدامه لكل الطلبات طوال عمر التطبيق** — لا تشغيل/
إغلاق لكل مستند (بطيء جداً على السيرفر). Playwright غير متزامن أصلاً
(async API)؛ بقية هذا المشروع متزامن بالكامل (كل مسارات FastAPI `def` لا
`async def`، SQLAlchemy متزامنة). الحل: خيط خلفي واحد مخصَّص يشغّل حلقة
asyncio واحدة طوال عمر التطبيق ويملك المتصفح؛ كل طلب توليد (من أي خيط
عامل FastAPI) يُسلَّم إلى تلك الحلقة عبر `run_coroutine_threadsafe`
ويُنتظَر متزامناً — نفس نمط الجسر القياسي بين كود متزامن ومكتبة async
وحيدة الخيط.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Optional

from playwright.async_api import Browser, Playwright, async_playwright

_loop: Optional[asyncio.AbstractEventLoop] = None
_thread: Optional[threading.Thread] = None
_browser: Optional[Browser] = None
_playwright_ctx: Optional[Playwright] = None


class RenderEngineNotStartedError(Exception):
    pass


def start(timeout: float = 30.0) -> None:
    """يُستدعى مرة واحدة عند إقلاع التطبيق (`main.py` lifespan)."""
    global _loop, _thread
    if _thread is not None:
        return

    ready = threading.Event()
    error: list[BaseException] = []

    def _run() -> None:
        global _loop, _browser, _playwright_ctx
        loop = asyncio.new_event_loop()
        _loop = loop
        asyncio.set_event_loop(loop)

        async def _init() -> None:
            global _browser, _playwright_ctx
            _playwright_ctx = await async_playwright().start()
            _browser = await _playwright_ctx.chromium.launch()

        try:
            loop.run_until_complete(_init())
        except BaseException as exc:  # noqa: BLE001 — يُعاد رفعه في الخيط المستدعي
            error.append(exc)
        finally:
            ready.set()
        if not error:
            loop.run_forever()

    _thread = threading.Thread(target=_run, name="doc-render", daemon=True)
    _thread.start()
    if not ready.wait(timeout=timeout):
        raise RuntimeError("محرك التوليد لم يبدأ خلال المهلة المحدَّدة")
    if error:
        _thread = None
        raise error[0]


def stop(timeout: float = 30.0) -> None:
    global _loop, _thread, _browser, _playwright_ctx
    if _loop is None or _thread is None:
        return

    async def _shutdown() -> None:
        if _browser is not None:
            await _browser.close()
        if _playwright_ctx is not None:
            await _playwright_ctx.stop()

    asyncio.run_coroutine_threadsafe(_shutdown(), _loop).result(timeout=timeout)
    _loop.call_soon_threadsafe(_loop.stop)
    _thread.join(timeout=timeout)
    _loop = None
    _thread = None
    _browser = None
    _playwright_ctx = None


def _run_coro(coro):
    if _loop is None:
        raise RenderEngineNotStartedError("محرك التوليد غير مُشغَّل — استدعِ render.start() أولاً")
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=60)


def render_pdf(html: str, *, prefer_css_page_size: bool = True) -> bytes:
    """حجم الصفحة (A4 أو ٨٠مم حراري) يُحدَّد بـ`@page { size: ... }` داخل
    القالب نفسه — مصدر وحيد للحقيقة، لا تكرار هنا بمعامل `format`."""

    async def _do() -> bytes:
        assert _browser is not None
        page = await _browser.new_page()
        try:
            await page.set_content(html, wait_until="networkidle")
            await page.evaluate("document.fonts.ready")  # الخط المضمَّن (data: URI) قد لا يكتمل تطبيقه مع networkidle وحدها
            return await page.pdf(print_background=True, prefer_css_page_size=prefer_css_page_size)
        finally:
            await page.close()

    return _run_coro(_do())


def render_png(html: str, *, width: int, height: Optional[int] = None) -> bytes:
    """`height=None` → لقطة الصفحة الكاملة (بطاقة بمقاس ديناميكي مثلاً)؛
    `height` صريح → لقطة بمقاس ثابت (بطاقة رصيد بمقاس واتساب)."""

    async def _do() -> bytes:
        assert _browser is not None
        page = await _browser.new_page(viewport={"width": width, "height": height or 100})
        try:
            await page.set_content(html, wait_until="networkidle")
            await page.evaluate("document.fonts.ready")
            return await page.screenshot(full_page=(height is None))
        finally:
            await page.close()

    return _run_coro(_do())
