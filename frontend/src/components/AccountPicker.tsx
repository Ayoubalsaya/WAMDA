import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { AccountRef } from '../api/types'
import { useReferenceData } from '../hooks/useReferenceData'
import { formatAccountBalance } from '../lib/formatAmount'
import './AccountPicker.css'

// مكوّن اختيار حساب واحد مشترك — يستبدل كل `<select>` حساب في النظام
// (٢٠٢٦-٠٩-٢٢، طلب مالك): يعرض رصيد كل حساب حيّاً تحت اسمه (أخضر/أحمر/
// رمادي)، ويجلبه من الخادم من جديد في كل مرة تُفتح فيها القائمة — لا رصيد
// مخزَّن من وقت تحميل الصفحة أو من أول تحميل لهذا الحقل.
export type AccountPickerSpec =
  | { mode: 'operation'; operationType: string; field: string; currencyCode: string; locationCode?: string }
  | { mode: 'full' }

function specKey(spec: AccountPickerSpec | null): string {
  if (!spec) return ''
  return spec.mode === 'full' ? 'full' : `${spec.operationType}|${spec.field}|${spec.currencyCode}|${spec.locationCode ?? ''}`
}

async function fetchAccounts(spec: AccountPickerSpec): Promise<AccountRef[]> {
  if (spec.mode === 'full') return api.get<AccountRef[]>('/reference/accounts')
  const params = new URLSearchParams({
    operation_type: spec.operationType, field: spec.field, currency_code: spec.currencyCode,
  })
  if (spec.locationCode) params.set('location_code', spec.locationCode)
  return api.get<AccountRef[]>(`/reference/accounts/for-operation?${params}`)
}

interface AccountPickerProps {
  value: string
  onChange: (code: string, account?: AccountRef) => void
  label: string
  spec: AccountPickerSpec | null
  emptyMessage?: string
  // تصفية جانب العميل فوق نتيجة `mode: 'full'` — لحقل مثل «بند المصروف»
  // الذي يريد حسابات EXPENSE فقط ولا مواصفة تصفية خادمية له في account_filters.py
  typeFilter?: string[]
}

export function AccountPicker({ value, onChange, label, spec, emptyMessage, typeFilter }: AccountPickerProps) {
  const { currencies } = useReferenceData()
  const [items, setItems] = useState<AccountRef[]>([])
  const [fetchedOnce, setFetchedOnce] = useState(false)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const key = specKey(spec)
  // حارس تتابع الطلبات — بلا هذا، فتح القائمة بعد تغيّر متسارع للمعايير
  // (عملة ثم موقعين خلال أجزاء ثانية، كما يحدث فعلياً عند بناء الفلتر)
  // قد يُرجع رداً أقدم بعد رد أحدث فيمحو رصيداً/قائمة صحيحة بأخرى فارغة
  // قديمة — علّة حقيقية اكتُشفت أثناء التحقق الحي (٢٠٢٦-٠٩-٢٢): زر حساب
  // «تركيا» ظل معطَّلاً بصمت لأن رد فارغ سابق (قبل اختيار الموقع) وصل بعد
  // الرد الصحيح.
  const requestSeq = useRef(0)

  const load = useCallback(() => {
    const seq = ++requestSeq.current
    if (!spec) { setItems([]); setFetchedOnce(false); return }
    setLoading(true)
    fetchAccounts(spec)
      .then((rows) => {
        if (seq !== requestSeq.current) return
        setItems(typeFilter ? rows.filter((a) => typeFilter.includes(a.type)) : rows)
        setFetchedOnce(true)
      })
      .catch(() => {
        if (seq !== requestSeq.current) return
        setItems([]); setFetchedOnce(true)
      })
      .finally(() => {
        if (seq === requestSeq.current) setLoading(false)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, typeFilter?.join(',')])

  // جلب استباقي عند تغيّر المعايير (عملة/موقع) — لعرض رسالة الفراغ فوراً
  // دون انتظار فتح القائمة.
  useEffect(() => { load() }, [load])

  // ثم إعادة جلب حتمية عند كل فتح فعلي للقائمة — هذا هو الضمان الحقيقي
  // لحيوية الرصيد، لا الاعتماد على الجلب الاستباقي وحده.
  function handleToggle() {
    if (!spec) return
    if (!open) { load(); setQuery(''); setOpen(true) } else { setOpen(false) }
  }

  useEffect(() => {
    if (!open) return
    searchRef.current?.focus()
    function onDocClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  // Escape يُغلق هذه القائمة فقط — يجب أن يتوقف هنا عبر stopPropagation
  // ولا يكمل صعوده، وإلا يصل لـOperationForm.handleKeyDown الذي يُفرِّغ
  // النموذج كاملاً عند Escape (علّة حقيقية اكتُشفت أثناء التحقق الحي:
  // إغلاق قائمة حساب كان يمسح كل حقول عملية التحويل بعمولة صامتاً).
  function handlePanelKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation()
      setOpen(false)
    }
  }

  const selected = items.find((a) => a.code === value)
  const visible = query.trim()
    ? items.filter((a) => a.code.includes(query.trim()) || a.name_ar.includes(query.trim()))
    : items
  const disabled = !spec || (fetchedOnce && items.length === 0 && !loading)

  return (
    <div className="field acct-picker" ref={rootRef} onKeyDown={handlePanelKeyDown}>
      <label className="field-label">{label}</label>
      <button
        type="button"
        className="acct-picker-trigger"
        disabled={disabled}
        onClick={handleToggle}
        aria-expanded={open}
      >
        {selected ? (
          <span className="acct-picker-trigger-value">{selected.code} — {selected.name_ar}</span>
        ) : (
          <span className="acct-picker-trigger-placeholder">
            {!spec ? (emptyMessage ?? 'غير متاح بعد') : loading && !fetchedOnce ? '...جارٍ التحميل' : (items.length ? 'اختر حساباً' : (emptyMessage ?? 'لا حسابات مطابقة'))}
          </span>
        )}
        <span className="acct-picker-trigger-caret" aria-hidden="true">▾</span>
      </button>

      {open && (
        <div className="acct-picker-panel">
          {loading && <div className="acct-picker-loading">...جارٍ تحديث الأرصدة</div>}
          {!loading && items.length > 5 && (
            <input
              ref={searchRef}
              className="acct-picker-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="ابحث بالاسم أو الكود..."
            />
          )}
          {!loading && (
            <div className="acct-picker-list">
              {visible.map((a) => {
                const { text, tone } = formatAccountBalance(a.balance, a.currency_code, currencies)
                return (
                  <button
                    type="button"
                    key={a.code}
                    className={`acct-picker-row${a.code === value ? ' is-selected' : ''}`}
                    onClick={() => { onChange(a.code, a); setOpen(false) }}
                  >
                    <span className="acct-picker-row-main">
                      <span className="acct-picker-row-name">{a.name_ar}</span>
                      <span className="acct-picker-row-code num text-muted">{a.code}</span>
                    </span>
                    <span className={`acct-picker-row-balance num tone-${tone}`}>
                      {text}{a.currency_code ? ` ${a.currency_code}` : ''}
                    </span>
                  </button>
                )
              })}
              {visible.length === 0 && <div className="acct-picker-empty">لا نتائج مطابقة</div>}
            </div>
          )}
        </div>
      )}

      {/* رسالة الفراغ تظهر مرة واحدة فقط — داخل الحقل نفسه (placeholder الزر أعلاه)؛ كانت تتكرر هنا تحته أيضاً */}
    </div>
  )
}
