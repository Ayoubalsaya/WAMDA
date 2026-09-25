import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { api } from '../api/client'
import type { JournalEntryOut } from '../api/types'
import { type SearchChip, chipsToParams } from '../lib/parseSearchQuery'
import { EditedBadge, EntryActionsBar } from './EntryActions'
import './SearchResultsPanel.css'

const OP_LABELS: Record<string, string> = {
  RECEIPT: 'قبض', PAYMENT: 'صرف', EXCHANGE: 'صرافة', CASH_TRANSFER: 'تحويل بعمولة',
  LOCAL_MOVE: 'نقل داخلي', REMIT_OUT: 'إرسال خارجي', SWIFT_OUT: 'سويفت خروج', SWIFT_IN: 'سويفت وصول',
  SWIFT_RETURN: 'سويفت مرتجع', EXPENSE: 'مصروف', OPENING: 'رصيد افتتاحي', ADJUSTMENT: 'تسوية',
}

interface SearchResultsPanelProps {
  chips: SearchChip[]
  onRemoveChip: (id: string) => void
  onClose: () => void
  currentUserRole: 'ADMIN' | 'ACCOUNTANT'
}

export function SearchResultsPanel({ chips, onRemoveChip, onClose, currentUserRole }: SearchResultsPanelProps) {
  const [results, setResults] = useState<JournalEntryOut[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [includeReversed, setIncludeReversed] = useState(false)

  async function reload() {
    if (chips.length === 0) {
      setResults(null)
      return
    }
    setLoading(true)
    const params = { ...chipsToParams(chips), include_reversed: String(includeReversed) }
    const search = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][])
    const rows = await api.get<JournalEntryOut[]>(`/search?${search.toString()}`)
    setResults(rows)
    setLoading(false)
  }

  useEffect(() => { void reload() }, [chips, includeReversed])

  return (
    <div className="modal-veil" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="search-results-panel card" onClick={(e) => e.stopPropagation()}>
        <div className="search-results-header">
          <h3 className="screen-title" style={{ fontSize: 17 }}>نتائج البحث</h3>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer' }}>
            <input type="checkbox" checked={includeReversed} onChange={(e) => setIncludeReversed(e.target.checked)} />
            إظهار الملغاة
          </label>
          <button type="button" className="btn btn-muted" style={{ width: 34, height: 34, padding: 0 }} onClick={onClose} aria-label="إغلاق">
            <X size={16} strokeWidth={1.9} />
          </button>
        </div>

        <div className="search-chips-row">
          {chips.map((chip) => (
            <span key={chip.id} className="search-chip">
              {chip.label}
              <button type="button" onClick={() => onRemoveChip(chip.id)} aria-label={`إزالة ${chip.label}`}>
                <X size={12} strokeWidth={2} />
              </button>
            </span>
          ))}
          {chips.length === 0 && <span className="text-muted" style={{ fontSize: 13 }}>اكتب في شريط البحث لإضافة رقائق</span>}
        </div>

        {loading && <p className="text-muted">...جارٍ البحث</p>}
        {!loading && results && results.length === 0 && <p className="text-muted">لا نتائج مطابقة</p>}
        {!loading && results && results.length > 0 && (
          <div className="search-results-list">
            <table className="data-table">
              <thead><tr><th>التاريخ</th><th>القيد</th><th>النوع</th><th>العميل</th><th>البيان</th><th></th></tr></thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.id} style={r.status === 'REVERSED' ? { opacity: 0.55 } : undefined}>
                    <td className="num">{r.entry_date}</td>
                    <td className="num">{r.entry_no}</td>
                    <td style={r.status === 'REVERSED' ? { textDecoration: 'line-through' } : undefined}>
                      {OP_LABELS[r.operation_type] ?? r.operation_type}
                    </td>
                    <td>{r.client_name_ar ?? '—'}</td>
                    <td>{r.description ?? '—'}</td>
                    <td style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      {r.status === 'REVERSED' && <span className="badge badge-status-reversed">ملغاة</span>}
                      {r.replaces_entry_id && <EditedBadge entryId={r.id} />}
                      <EntryActionsBar entry={r} currentUserRole={currentUserRole} onChanged={reload} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
