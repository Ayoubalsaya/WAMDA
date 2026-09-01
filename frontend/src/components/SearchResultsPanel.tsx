import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { api } from '../api/client'
import type { JournalEntryOut } from '../api/types'
import { type SearchChip, chipsToParams } from '../lib/parseSearchQuery'
import './SearchResultsPanel.css'

const OP_LABELS: Record<string, string> = {
  RECEIPT: 'قبض', PAYMENT: 'صرف', EXCHANGE: 'صرافة', CASH_TRANSFER: 'تحويل بعمولة',
  LOCAL_MOVE: 'نقل داخلي', REMIT_OUT: 'إرسال لمستفيد', SWIFT_OUT: 'سويفت خروج', SWIFT_IN: 'سويفت وصول',
  SWIFT_RETURN: 'سويفت مرتجع', EXPENSE: 'مصروف', OPENING: 'رصيد افتتاحي', ADJUSTMENT: 'تسوية',
}

interface SearchResultsPanelProps {
  chips: SearchChip[]
  onRemoveChip: (id: string) => void
  onClose: () => void
}

export function SearchResultsPanel({ chips, onRemoveChip, onClose }: SearchResultsPanelProps) {
  const [results, setResults] = useState<JournalEntryOut[] | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (chips.length === 0) {
      setResults(null)
      return
    }
    setLoading(true)
    const params = chipsToParams(chips)
    const search = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][])
    void api.get<JournalEntryOut[]>(`/search?${search.toString()}`).then((rows) => {
      setResults(rows)
      setLoading(false)
    })
  }, [chips])

  return (
    <div className="modal-veil" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="search-results-panel card" onClick={(e) => e.stopPropagation()}>
        <div className="search-results-header">
          <h3 className="screen-title" style={{ fontSize: 17 }}>نتائج البحث</h3>
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
              <thead><tr><th>التاريخ</th><th>القيد</th><th>النوع</th><th>العميل</th><th>البيان</th></tr></thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.id}>
                    <td className="num">{r.entry_date}</td>
                    <td className="num">{r.entry_no}</td>
                    <td>{OP_LABELS[r.operation_type] ?? r.operation_type}</td>
                    <td>{r.client_name_ar ?? '—'}</td>
                    <td>{r.description ?? '—'}</td>
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
