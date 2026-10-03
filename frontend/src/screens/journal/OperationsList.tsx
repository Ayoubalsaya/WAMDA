import { useCallback, useEffect, useMemo, useState } from 'react'
import Decimal from 'decimal.js'
import {
  ArrowDownUp, Ban, ChevronLeft, ChevronRight, CreditCard, Eye, HandCoins, Landmark, PlusCircle, Receipt, Repeat, Scale, Send, Wallet2,
} from 'lucide-react'
import { api } from '../../api/client'
import type { JournalEntryOut } from '../../api/types'
import { CommentsPanel, EditedBadge, EntryActionsBar } from '../../components/EntryActions'
import { SegmentedTabs } from '../../components/SegmentedTabs'
import { useReferenceData } from '../../hooks/useReferenceData'
import { formatAmount } from '../../lib/formatAmount'
import { lineAmount } from '../../lib/lineAmount'
import './journal-design.css'

const OP_LABELS: Record<string, string> = {
  RECEIPT: 'قبض', PAYMENT: 'صرف', EXCHANGE: 'صرافة', CASH_TRANSFER: 'تحويل بعمولة',
  LOCAL_MOVE: 'نقل داخلي', REMIT_OUT: 'إرسال خارجي', SWIFT_OUT: 'سويفت خروج', SWIFT_IN: 'سويفت وصول',
  SWIFT_RETURN: 'سويفت مرتجع', EXPENSE: 'مصروف', OPENING: 'رصيد افتتاحي', ADJUSTMENT: 'تسوية',
}

// نفس أيقونة/لون كل نوع عملية في OperationForm.tsx وNewOperationPanel.tsx —
// هوية بصرية واحدة عبر الشاشة كلها. مُكرَّرة هنا محلياً عمداً (لا وحدة
// مشتركة بعد) — أي تعديل على أيقونة نوع هناك يجب أن يُطابَق هنا يدوياً.
const OP_ICON: Record<string, typeof HandCoins> = {
  RECEIPT: HandCoins, PAYMENT: Wallet2, EXCHANGE: ArrowDownUp, CASH_TRANSFER: Repeat,
  REMIT_OUT: Send, EXPENSE: Receipt, SWIFT_OUT: Send, SWIFT_IN: Landmark, SWIFT_RETURN: Ban,
  LOCAL_MOVE: CreditCard, OPENING: PlusCircle, ADJUSTMENT: Scale,
}
const OP_TONE: Record<string, string> = {
  RECEIPT: 'in', PAYMENT: 'out', EXCHANGE: 'exchange', CASH_TRANSFER: 'neutral',
  REMIT_OUT: 'commission', EXPENSE: 'neutral', SWIFT_OUT: 'neutral', SWIFT_IN: 'neutral',
  SWIFT_RETURN: 'out', LOCAL_MOVE: 'neutral', OPENING: 'neutral', ADJUSTMENT: 'exchange',
}

function todayInTripoli(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Tripoli' }).format(new Date())
}

// حساب تقويمي بحت عبر UTC — لا `new Date(iso)` محلي (قد يزحزح اليوم يوماً
// كاملاً حسب فرق توقيت المتصفح عن الخادم، نفس فخّ todayInTripoli أعلاه).
function addDays(isoDate: string, delta: number): string {
  const [y, m, d] = isoDate.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + delta)).toISOString().slice(0, 10)
}

type ViewMode = 'day' | 'range'

interface OperationsListProps {
  currentUserRole: 'ADMIN' | 'ACCOUNTANT'
  refreshToken: number // يرتفع من الأب (JournalScreen) عند ترحيل عملية جديدة
}

export function OperationsList({ currentUserRole, refreshToken }: OperationsListProps) {
  const { currencies } = useReferenceData()
  const [mode, setMode] = useState<ViewMode>('day')
  const [selectedDate, setSelectedDate] = useState(() => todayInTripoli())
  const [rangeFrom, setRangeFrom] = useState(() => addDays(todayInTripoli(), -6))
  const [rangeTo, setRangeTo] = useState(() => todayInTripoli())
  const [includeReversed, setIncludeReversed] = useState(false)
  const [entries, setEntries] = useState<JournalEntryOut[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    const params = new URLSearchParams({ include_reversed: String(includeReversed) })
    if (mode === 'day') params.set('date', selectedDate)
    else { params.set('date_from', rangeFrom); params.set('date_to', rangeTo) }
    const rows = await api.get<JournalEntryOut[]>(`/journal/entries?${params}`)
    setEntries(rows)
    setLoading(false)
  }, [mode, selectedDate, rangeFrom, rangeTo, includeReversed])

  useEffect(() => { void reload() }, [reload, refreshToken])

  const profitTotals = useMemo(() => {
    const totals = new Map<string, Decimal>()
    for (const e of entries) {
      if (!e.profit_amount || !e.profit_currency) continue
      totals.set(e.profit_currency, (totals.get(e.profit_currency) ?? new Decimal(0)).plus(e.profit_amount))
    }
    return [...totals.entries()]
  }, [entries])

  const isToday = mode === 'day' && selectedDate === todayInTripoli()

  return (
    <aside className="journal-col journal-col-left">
      <section className="jr-panel activity-panel">
        <div className="dock-heading">
          <div>
            <span className="panel-kicker">السجل</span>
            <h3>سجل العمليات</h3>
          </div>
          <label className="toggle-line">
            <input type="checkbox" checked={includeReversed} onChange={(e) => setIncludeReversed(e.target.checked)} />
            إظهار الملغاة
          </label>
        </div>

        <SegmentedTabs
          variant="pill" ariaLabel="عرض السجل" value={mode} onChange={setMode}
          items={[{ id: 'day', label: 'يوم' }, { id: 'range', label: 'نطاق' }]}
        />

        {mode === 'day' ? (
          <>
            <div className="date-control">
              <button type="button" title="اليوم السابق" onClick={() => setSelectedDate((d) => addDays(d, -1))}>
                <ChevronRight size={16} />
              </button>
              <input type="date" value={selectedDate} max={todayInTripoli()} onChange={(e) => setSelectedDate(e.target.value)} />
              <button type="button" title="اليوم التالي" disabled={isToday} onClick={() => setSelectedDate((d) => addDays(d, 1))}>
                <ChevronLeft size={16} />
              </button>
            </div>
            {!isToday && (
              <div className="date-today-link">
                <button type="button" className="btn-text" onClick={() => setSelectedDate(todayInTripoli())}>اليوم</button>
              </div>
            )}
          </>
        ) : (
          <div className="form-row" style={{ alignItems: 'center', marginTop: 10 }}>
            <input type="date" value={rangeFrom} max={rangeTo} onChange={(e) => setRangeFrom(e.target.value)} />
            <span className="text-muted">إلى</span>
            <input type="date" value={rangeTo} min={rangeFrom} max={todayInTripoli()} onChange={(e) => setRangeTo(e.target.value)} />
          </div>
        )}

        {!loading && (
          <div className="activity-summary">
            <span className="text-muted">{entries.length} عملية</span>
            {profitTotals.length > 0 && (
              <span className="num profits">
                {profitTotals.map(([ccy, total]) => (
                  <span key={ccy} className={total.isNegative() ? 'money-negative' : 'money-positive'}>
                    {formatAmount(total.toString(), ccy, currencies)} {ccy}
                  </span>
                ))}
              </span>
            )}
          </div>
        )}

        {loading && <p className="text-muted">...جارٍ التحميل</p>}
        {!loading && entries.length === 0 && <p className="activity-empty">لا عمليات في هذا النطاق</p>}
        <div className="activity-list">
          {entries.map((entry) => {
            const isReversed = entry.status === 'REVERSED'
            const Icon = OP_ICON[entry.operation_type] ?? Receipt
            const tone = OP_TONE[entry.operation_type] ?? 'neutral'
            return (
              <div key={entry.id} className={`activity-row${isReversed ? ' is-reversed' : ''}`}>
                <button
                  type="button" className={`activity-item${isReversed ? ' is-reversed-label' : ''}`}
                  onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
                >
                  <span className={`activity-icon tone-${tone}`}><Icon size={16} strokeWidth={2} /></span>
                  <span className="activity-copy">
                    <strong>{OP_LABELS[entry.operation_type] ?? entry.operation_type}</strong>
                    <small>
                      {entry.client_name_ar ?? entry.entry_no}
                      {mode === 'range' && <span className="num"> · {entry.entry_date}</span>}
                    </small>
                  </span>
                  <span className="activity-side">
                    {isReversed && <span className="badge badge-status-reversed">ملغاة</span>}
                    {entry.replaces_entry_id && <EditedBadge entryId={entry.id} />}
                    {entry.chain_ref && <span className="badge badge-chain">{entry.chain_ref}</span>}
                    <Eye size={16} strokeWidth={1.9} />
                  </span>
                </button>
                {expandedId === entry.id && (
                  <div className="activity-detail">
                    <div className="num detail-head">{entry.entry_no} · {entry.entry_date}</div>
                    {entry.note && (
                      <div className="detail-line">
                        <span className="text-muted">ملاحظة</span>
                        <span>{entry.note}</span>
                      </div>
                    )}
                    {entry.lines.map((line, i) => {
                      const a = lineAmount(line, currencies)
                      return (
                        <div key={i} className="detail-line" data-testid="entry-line" data-side={a.side}>
                          <span>{line.account_name_ar}</span>
                          <span className="line-amount">
                            <span className={`line-dir is-${a.side}`}>{a.label}</span>
                            <span className="num" data-testid="line-amount" dir="ltr">{a.text}</span>
                            <span className="text-muted num">{line.currency_code}</span>
                          </span>
                        </div>
                      )
                    })}
                    {entry.profit_amount && (
                      <div className="detail-line">
                        <span>ربح العملية</span>
                        <span className={`num ${Number(entry.profit_amount) >= 0 ? 'money-positive' : 'money-negative'}`}>
                          {formatAmount(entry.profit_amount, entry.profit_currency ?? '', currencies)} {entry.profit_currency}
                        </span>
                      </div>
                    )}
                    {entry.client_name_ar && entry.status === 'POSTED' && (
                      <div className="detail-links">
                        <a href={`/documents/receipt/${entry.id}.pdf`} target="_blank" rel="noreferrer" className="btn-text">طباعة A4</a>
                        <a href={`/documents/receipt/${entry.id}.pdf?size=thermal`} target="_blank" rel="noreferrer" className="btn-text">طباعة حراري</a>
                        <a href={`/documents/receipt/${entry.id}.png`} target="_blank" rel="noreferrer" className="btn-text">صورة</a>
                      </div>
                    )}
                    {entry.chain_ref && (
                      <div className="detail-links">
                        <a href={`/documents/chain-summary/${entry.chain_ref}.pdf`} target="_blank" rel="noreferrer" className="btn-text">ملخص السلسلة PDF</a>
                        <a href={`/documents/chain-summary/${entry.chain_ref}.png`} target="_blank" rel="noreferrer" className="btn-text">صورة</a>
                      </div>
                    )}
                    {entry.status === 'POSTED' && (
                      <div className="detail-links">
                        <EntryActionsBar entry={entry} currentUserRole={currentUserRole} onChanged={() => void reload()} />
                      </div>
                    )}
                    <CommentsPanel entryId={entry.id} />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </section>
    </aside>
  )
}
