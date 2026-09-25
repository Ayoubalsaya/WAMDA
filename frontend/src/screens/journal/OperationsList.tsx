import { useCallback, useEffect, useMemo, useState } from 'react'
import Decimal from 'decimal.js'
import { ChevronLeft, ChevronRight, Eye } from 'lucide-react'
import { api } from '../../api/client'
import type { JournalEntryOut } from '../../api/types'
import { CommentsPanel, EditedBadge, EntryActionsBar } from '../../components/EntryActions'

const OP_LABELS: Record<string, string> = {
  RECEIPT: 'قبض', PAYMENT: 'صرف', EXCHANGE: 'صرافة', CASH_TRANSFER: 'تحويل بعمولة',
  LOCAL_MOVE: 'نقل داخلي', REMIT_OUT: 'إرسال خارجي', SWIFT_OUT: 'سويفت خروج', SWIFT_IN: 'سويفت وصول',
  SWIFT_RETURN: 'سويفت مرتجع', EXPENSE: 'مصروف', OPENING: 'رصيد افتتاحي', ADJUSTMENT: 'تسوية',
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
      <div className="op-row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
        <div className="card-title">سجل العمليات</div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer' }}>
          <input type="checkbox" checked={includeReversed} onChange={(e) => setIncludeReversed(e.target.checked)} />
          إظهار الملغاة
        </label>
      </div>

      <div className="op-row" style={{ marginBottom: 8, gap: 6 }}>
        <button type="button" className={`op-tab${mode === 'day' ? ' is-active' : ''}`} onClick={() => setMode('day')}>يوم</button>
        <button type="button" className={`op-tab${mode === 'range' ? ' is-active' : ''}`} onClick={() => setMode('range')}>نطاق</button>
      </div>

      {mode === 'day' ? (
        <div className="op-row" style={{ marginBottom: 8, gap: 6, alignItems: 'center' }}>
          <button type="button" className="btn btn-secondary btn-sm" title="اليوم السابق" onClick={() => setSelectedDate((d) => addDays(d, -1))}>
            <ChevronRight size={16} />
          </button>
          <input type="date" value={selectedDate} max={todayInTripoli()} onChange={(e) => setSelectedDate(e.target.value)} style={{ flex: 1 }} />
          <button type="button" className="btn btn-secondary btn-sm" title="اليوم التالي" disabled={isToday} onClick={() => setSelectedDate((d) => addDays(d, 1))}>
            <ChevronLeft size={16} />
          </button>
          {!isToday && (
            <button type="button" className="btn-text" onClick={() => setSelectedDate(todayInTripoli())}>اليوم</button>
          )}
        </div>
      ) : (
        <div className="op-row" style={{ marginBottom: 8, gap: 6 }}>
          <input type="date" value={rangeFrom} max={rangeTo} onChange={(e) => setRangeFrom(e.target.value)} style={{ flex: 1 }} />
          <span className="text-muted">إلى</span>
          <input type="date" value={rangeTo} min={rangeFrom} max={todayInTripoli()} onChange={(e) => setRangeTo(e.target.value)} style={{ flex: 1 }} />
        </div>
      )}

      {!loading && (
        <div className="op-row" style={{ justifyContent: 'space-between', marginBottom: 10, fontSize: 12.5 }}>
          <span className="text-muted">{entries.length} عملية</span>
          {profitTotals.length > 0 && (
            <span className="num" style={{ display: 'flex', gap: 8 }}>
              {profitTotals.map(([ccy, total]) => (
                <span key={ccy} className={total.isNegative() ? 'money-negative' : 'money-positive'}>
                  {total.toFixed(3)} {ccy}
                </span>
              ))}
            </span>
          )}
        </div>
      )}

      {loading && <p className="text-muted">...جارٍ التحميل</p>}
      {!loading && entries.length === 0 && <p className="text-muted" style={{ fontSize: 13 }}>لا عمليات في هذا النطاق</p>}
      <div className="today-ops-list">
        {entries.map((entry) => {
          const isReversed = entry.status === 'REVERSED'
          return (
          <div key={entry.id} className="today-op-row" style={isReversed ? { opacity: 0.55 } : undefined}>
            <button type="button" className="today-op-summary" onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}>
              <div>
                <div className="today-op-type" style={isReversed ? { textDecoration: 'line-through' } : undefined}>
                  {OP_LABELS[entry.operation_type] ?? entry.operation_type}
                </div>
                <div className="text-muted" style={{ fontSize: 12 }}>
                  {entry.client_name_ar ?? entry.entry_no}
                  {mode === 'range' && <span className="num"> · {entry.entry_date}</span>}
                </div>
              </div>
              <div className="today-op-actions">
                {isReversed && <span className="badge badge-status-reversed">ملغاة</span>}
                {entry.replaces_entry_id && <EditedBadge entryId={entry.id} />}
                {entry.chain_ref && <span className="badge badge-chain">{entry.chain_ref}</span>}
                <Eye size={16} strokeWidth={1.9} />
              </div>
            </button>
            {expandedId === entry.id && (
              <div className="today-op-detail">
                <div className="num text-muted" style={{ fontSize: 12 }}>{entry.entry_no} · {entry.entry_date}</div>
                {entry.note && (
                  <div className="today-op-line">
                    <span className="text-muted">ملاحظة</span>
                    <span>{entry.note}</span>
                  </div>
                )}
                {entry.lines.map((line, i) => (
                  <div key={i} className="today-op-line">
                    <span>{line.account_name_ar}</span>
                    <span className={`num ${line.debit !== '0' && line.debit !== '0.00' && line.debit !== '0.000' ? 'money-negative' : 'money-positive'}`}>
                      {line.debit !== '0' && line.debit !== '0.00' && line.debit !== '0.000' ? line.debit : line.credit}
                    </span>
                  </div>
                ))}
                {entry.profit_amount && (
                  <div className="today-op-line">
                    <span>ربح العملية</span>
                    <span className={`num ${Number(entry.profit_amount) >= 0 ? 'money-positive' : 'money-negative'}`}>
                      {entry.profit_amount} {entry.profit_currency}
                    </span>
                  </div>
                )}
                {entry.client_name_ar && entry.status === 'POSTED' && (
                  <div className="today-op-print-row">
                    <a href={`/documents/receipt/${entry.id}.pdf`} target="_blank" rel="noreferrer" className="btn-text">طباعة A4</a>
                    <a href={`/documents/receipt/${entry.id}.pdf?size=thermal`} target="_blank" rel="noreferrer" className="btn-text">طباعة حراري</a>
                    <a href={`/documents/receipt/${entry.id}.png`} target="_blank" rel="noreferrer" className="btn-text">صورة</a>
                  </div>
                )}
                {entry.chain_ref && (
                  <div className="today-op-print-row">
                    <a href={`/documents/chain-summary/${entry.chain_ref}.pdf`} target="_blank" rel="noreferrer" className="btn-text">ملخص السلسلة PDF</a>
                    <a href={`/documents/chain-summary/${entry.chain_ref}.png`} target="_blank" rel="noreferrer" className="btn-text">صورة</a>
                  </div>
                )}
                {entry.status === 'POSTED' && (
                  <div className="today-op-print-row">
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
    </aside>
  )
}
