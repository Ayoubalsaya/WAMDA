import { useState } from 'react'
import { Eye } from 'lucide-react'
import type { JournalEntryOut } from '../../api/types'
import { CommentsPanel, EditedBadge, EntryActionsBar } from '../../components/EntryActions'

const OP_LABELS: Record<string, string> = {
  RECEIPT: 'قبض', PAYMENT: 'صرف', EXCHANGE: 'صرافة', CASH_TRANSFER: 'تحويل بعمولة',
  LOCAL_MOVE: 'نقل داخلي', REMIT_OUT: 'إرسال', SWIFT_OUT: 'سويفت خروج', SWIFT_IN: 'سويفت وصول',
  SWIFT_RETURN: 'سويفت مرتجع', EXPENSE: 'مصروف', OPENING: 'رصيد افتتاحي', ADJUSTMENT: 'تسوية',
}

interface OperationsListProps {
  entries: JournalEntryOut[]
  loading: boolean
  onEntryChanged: () => void
  includeReversed: boolean
  onIncludeReversedChange: (v: boolean) => void
  currentUserRole: 'ADMIN' | 'ACCOUNTANT'
}

export function OperationsList({ entries, loading, onEntryChanged, includeReversed, onIncludeReversedChange, currentUserRole }: OperationsListProps) {
  const [expandedId, setExpandedId] = useState<number | null>(null)

  return (
    <aside className="journal-col journal-col-left">
      <div className="op-row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
        <div className="card-title">عمليات اليوم</div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer' }}>
          <input type="checkbox" checked={includeReversed} onChange={(e) => onIncludeReversedChange(e.target.checked)} />
          إظهار الملغاة
        </label>
      </div>
      {loading && <p className="text-muted">...جارٍ التحميل</p>}
      {!loading && entries.length === 0 && <p className="text-muted" style={{ fontSize: 13 }}>لا عمليات اليوم بعد</p>}
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
                <div className="text-muted" style={{ fontSize: 12 }}>{entry.client_name_ar ?? entry.entry_no}</div>
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
                <div className="num text-muted" style={{ fontSize: 12 }}>{entry.entry_no}</div>
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
                    <EntryActionsBar entry={entry} currentUserRole={currentUserRole} onChanged={onEntryChanged} />
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
