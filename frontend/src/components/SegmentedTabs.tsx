import type { ReactNode } from 'react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import './SegmentedTabs.css'

/* SegmentedTabs — الكبسولة المتمددة الموحَّدة لكل أزرار التبويب في النظام
 * (طلب مالك ٢٠٢٦-٠٩-٢٧، مرجعه "Liquid Glass / Opal"). مكوّن واحد يُستخدم
 * في: أنواع العمليات باليومية (dock) · نطاق الصرافة ويوم/نطاق السجل
 * وتبويبات العملات وتبويبات الإعدادات/التقارير (pill) · الشريط الجانبي
 * رأسياً (rail). لا نسخة ثانية من منطق الحركة في أي مكان.
 *
 * ═══ الميكانيكا ═══
 * كبسولة خلفية (`.seg-pill`) تُحرَّك بنابضين مستقلّين — نابض لكل حافة من
 * حافتي الكبسولة (البداية/النهاية على المحور: أفقي لـdock/pill، رأسي
 * لـrail). عند الانتقال، الحافة التي تتجه نحوها الحركة ("الأمامية") تأخذ
 * صلابة أعلى (stiffness≈230) فتصل أولاً؛ الحافة الأخرى ("الخلفية") أليَن
 * (stiffness≈128) فتتأخر — فارق السرعة هذا ينتج تمدداً حقيقياً في منتصف
 * الرحلة (الكبسولة أعرض من حجمها المستقر مؤقتاً) ثم انكماشاً عند الوصول،
 * بلا أي حركة توقيتية مصطنعة (keyframes) — فيزياء نابض فعلية بخطوة زمنية
 * ثابتة عبر requestAnimationFrame. انضغاط رأسي خفيف (scaleY أو scaleX
 * لـrail) يتناسب مباشرة مع مقدار التمدد الفعلي فقط، يعود لـ١ عند الاستقرار.
 *
 * لون النص/الأيقونة عند المرور: بدل تلوين كل حرف (مكلف ويحتاج canvas)،
 * الصف الحقيقي (القابل للنقر، دائماً بلونه الخامل) يُغطَّى بنسخة طبق
 * الأصل منه بلونها "النشط" دائماً، داخل نافذة قصّ (`overflow:hidden`)
 * بحجم الكبسولة بالضبط تتحرك معه — أرخص من clip-path محسوب لكل زر، ونفس
 * الأثر البصري تماماً: حافة الكبسولة "تلوّن" النص وهي تمرّ عليه.
 *
 * الإدخال لا ينتظر الحركة أبداً: onChange يُستدعى فوراً عند النقر/السهم،
 * قبل أي رسم متحرك — الحركة تُزيّن حالة مُحدَّثة بالفعل، لا تُعطّلها.
 */

export interface SegTabItem<T extends string> {
  id: T
  label: string
  icon?: ReactNode
  /** لاحقة صنف لون الأيقونة (تُطابق .tab-icon.tone-* الحالية) — dock فقط. */
  tone?: string
  /** تلميح hover (مثال: تسمية + اختصار لوحة مفاتيح) — لا بديل مرئي للـlabel. */
  title?: string
}

type Variant = 'dock' | 'pill' | 'rail'

interface SegmentedTabsProps<T extends string> {
  items: SegTabItem<T>[]
  value: T
  /** el: زر التبويب المنقور/المُختار فعلياً — لازم لمن يحتاج نقطة أصل
   * بصرية للتنقّل (مثال: الشريط الجانبي، أصل انتقال الشاشة). اختياري. */
  onChange: (id: T, el?: HTMLButtonElement) => void
  ariaLabel: string
  variant?: Variant
  className?: string
}

interface Edge { pos: number; vel: number; target: number; k: number }

const DAMPING_RATIO = 1 // حرج — بلا اهتزاز/ارتداد، فارق الصلابة وحده ينتج التمدد
const LEADING_K = 230
const TRAILING_K = 128
const EPSILON = 0.4
const MAX_DURATION_MS = 420
const DT = 1 / 60 // خطوة ثابتة — أكثر استقراراً عددياً من dt الحقيقي المتذبذب بين الإطارات

function stepEdge(e: Edge): void {
  const c = 2 * Math.sqrt(e.k) * DAMPING_RATIO
  const force = -e.k * (e.pos - e.target) - c * e.vel
  e.vel += (force * DT) / 1
  e.pos += e.vel * DT
}
function settled(e: Edge): boolean {
  return Math.abs(e.pos - e.target) < EPSILON && Math.abs(e.vel) < EPSILON
}

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = () => setReduced(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return reduced
}

export function SegmentedTabs<T extends string>({
  items, value, onChange, ariaLabel, variant = 'pill', className,
}: SegmentedTabsProps<T>) {
  const orientation: 'horizontal' | 'vertical' = variant === 'rail' ? 'vertical' : 'horizontal'
  const containerRef = useRef<HTMLDivElement>(null)
  const pillRef = useRef<HTMLDivElement>(null)
  const windowRef = useRef<HTMLDivElement>(null)
  const innerRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef(new Map<string, HTMLButtonElement>())
  const startEdge = useRef<Edge>({ pos: 0, vel: 0, target: 0, k: TRAILING_K })
  const endEdge = useRef<Edge>({ pos: 0, vel: 0, target: 0, k: LEADING_K })
  const rafRef = useRef<number | null>(null)
  const deadlineRef = useRef(0)
  const initedRef = useRef(false)
  const reducedMotion = useReducedMotion()

  const measure = useCallback((id: string): [number, number] | null => {
    const el = itemRefs.current.get(id)
    const container = containerRef.current
    if (!el || !container) return null
    const er = el.getBoundingClientRect()
    const cr = container.getBoundingClientRect()
    return orientation === 'horizontal' ? [er.left - cr.left, er.right - cr.left] : [er.top - cr.top, er.bottom - cr.top]
  }, [orientation])

  const paint = useCallback((scale: number) => {
    const pill = pillRef.current
    const win = windowRef.current
    const inner = innerRef.current
    if (!pill || !win || !inner) return
    const s = startEdge.current.pos
    const e = endEdge.current.pos
    const size = Math.max(0, e - s)
    if (orientation === 'horizontal') {
      pill.style.transform = `translateX(${s}px) scaleY(${scale})`
      pill.style.width = `${size}px`
      win.style.transform = `translateX(${s}px)`
      win.style.width = `${size}px`
      inner.style.transform = `translateX(${-s}px)`
    } else {
      pill.style.transform = `translateY(${s}px) scaleX(${scale})`
      pill.style.height = `${size}px`
      win.style.transform = `translateY(${s}px)`
      win.style.height = `${size}px`
      inner.style.transform = `translateY(${-s}px)`
    }
  }, [orientation])

  const tick = useCallback((now: number) => {
    stepEdge(startEdge.current)
    stepEdge(endEdge.current)
    const finalSize = endEdge.current.target - startEdge.current.target
    const currentSize = endEdge.current.pos - startEdge.current.pos
    const overshoot = finalSize > 0 ? Math.max(0, currentSize / finalSize - 1) : 0
    const scale = 1 - Math.min(overshoot * 1.2, 0.06) // ٠.٩٤ عند التمدد الأقصى المعتاد
    const done = (settled(startEdge.current) && settled(endEdge.current)) || now >= deadlineRef.current
    if (done) {
      startEdge.current.pos = startEdge.current.target
      endEdge.current.pos = endEdge.current.target
      paint(1)
      rafRef.current = null
      return
    }
    paint(scale)
    rafRef.current = requestAnimationFrame(tick)
  }, [paint])

  const hidePill = useCallback(() => {
    // القيمة الحالية ليست ضمن عناصر هذه المجموعة (مجموعة تبويبات أخرى
    // نشطة، مثال: صفّ المستوى الأول أثناء تفعيل تبويب من صفّ «المزيد») —
    // إخفاء الكبسولة بدل تجميدها في آخر موضع صحيح (وهم اختيار خاطئ).
    initedRef.current = false
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
    const pill = pillRef.current
    const win = windowRef.current
    if (pill) pill.style.opacity = '0'
    if (win) win.style.opacity = '0'
  }, [])

  const retarget = useCallback((id: string, snap: boolean) => {
    const bounds = measure(id)
    if (!bounds) { hidePill(); return }
    const pill = pillRef.current
    const win = windowRef.current
    if (pill) pill.style.opacity = ''
    if (win) win.style.opacity = ''
    const [a, b] = bounds
    if (snap || !initedRef.current) {
      startEdge.current = { pos: a, vel: 0, target: a, k: TRAILING_K }
      endEdge.current = { pos: b, vel: 0, target: b, k: LEADING_K }
      initedRef.current = true
      if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
      paint(1)
      return
    }
    const prevCenter = (startEdge.current.target + endEdge.current.target) / 2
    const newCenter = (a + b) / 2
    const movingForward = newCenter >= prevCenter // "أمام" = جهة الإحداثي الأكبر (يمين/أسفل)
    startEdge.current.target = a
    endEdge.current.target = b
    startEdge.current.k = movingForward ? TRAILING_K : LEADING_K
    endEdge.current.k = movingForward ? LEADING_K : TRAILING_K
    if (reducedMotion) {
      startEdge.current.pos = a; startEdge.current.vel = 0
      endEdge.current.pos = b; endEdge.current.vel = 0
      if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
      paint(1)
      return
    }
    deadlineRef.current = performance.now() + MAX_DURATION_MS
    if (!rafRef.current) rafRef.current = requestAnimationFrame(tick)
  }, [measure, paint, reducedMotion, tick, hidePill])

  // إعادة الاستهداف عند تغيّر التبويب النشط — انتقال نابض حقيقي
  useLayoutEffect(() => {
    retarget(value, false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  // إعادة حساب المواضع عند تغيّر حجم الحاوية أو عدد/أبعاد العناصر
  // (ظهور صف «المزيد»، تغيّر حجم النافذة) — قفزة فورية لا حركة نابضية،
  // هذا تصحيح تخطيط لا انتقال اختيار.
  useEffect(() => {
    const container = containerRef.current
    if (!container || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => retarget(value, true))
    ro.observe(container)
    itemRefs.current.forEach((el) => ro.observe(el))
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items.length])

  useEffect(() => () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }, [])

  // لوحة المفاتيح: الأسهم تنقل بين التبويبات — معكوسة أفقياً في RTL
  // (يمين=البداية بصرياً)، عمودياً بلا انعكاس. الاختيار فوري، الحركة تتبعه.
  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const idx = items.findIndex((it) => it.id === value)
    if (idx === -1) return
    let dir = 0
    if (orientation === 'horizontal') {
      const rtl = containerRef.current ? getComputedStyle(containerRef.current).direction === 'rtl' : true
      if (e.key === 'ArrowRight') dir = rtl ? -1 : 1
      else if (e.key === 'ArrowLeft') dir = rtl ? 1 : -1
    } else {
      if (e.key === 'ArrowDown') dir = 1
      else if (e.key === 'ArrowUp') dir = -1
    }
    if (dir === 0) return
    e.preventDefault()
    const next = items[(idx + dir + items.length) % items.length]
    const nextEl = itemRefs.current.get(next.id)
    onChange(next.id, nextEl)
    nextEl?.focus()
  }

  function renderRow(activeOverlay: boolean) {
    return items.map((it) => (
      <button
        key={it.id}
        ref={activeOverlay ? undefined : (el) => { if (el) itemRefs.current.set(it.id, el); else itemRefs.current.delete(it.id) }}
        type="button"
        role={activeOverlay ? undefined : 'tab'}
        aria-selected={activeOverlay ? undefined : value === it.id}
        aria-hidden={activeOverlay || undefined}
        tabIndex={activeOverlay ? -1 : (value === it.id ? 0 : -1)}
        className={`seg-tab${value === it.id ? ' is-active' : ''}`}
        title={activeOverlay ? undefined : it.title}
        onClick={activeOverlay ? undefined : (e) => onChange(it.id, e.currentTarget)}
      >
        {it.icon && <span className={`tab-icon${it.tone ? ` tone-${it.tone}` : ''}`}>{it.icon}</span>}
        {it.label && <span>{it.label}</span>}
      </button>
    ))
  }

  return (
    <div
      ref={containerRef}
      className={`seg-tabs seg-tabs-${variant} seg-tabs-${orientation}${className ? ` ${className}` : ''}`}
      role="tablist"
      aria-label={ariaLabel}
      aria-orientation={orientation}
      onKeyDown={handleKeyDown}
    >
      <div ref={pillRef} className="seg-pill" aria-hidden="true" />
      <div className="seg-row seg-row-base">{renderRow(false)}</div>
      <div ref={windowRef} className="seg-clip-window" aria-hidden="true">
        <div ref={innerRef} className="seg-row seg-row-overlay">{renderRow(true)}</div>
      </div>
    </div>
  )
}
