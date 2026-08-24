import { useState } from 'react'
import { Eye } from 'lucide-react'
import type { JournalEntryOut } from '../../api/types'

const OP_LABELS: Record<string, string> = {
  RECEIPT: 'قبض', PAYMENT: 'صرف', EXCHANGE: 'صرافة', CASH_TRANSFER: 'تحويل بعمولة',
  LOCAL_MOVE: 'نقل داخلي', REMIT_OUT: 'إرسال', SWIFT_OUT: 'سويفت خروج', SWIFT_IN: 'سويفت وصول',
  SWIFT_RETURN: 'سويفت مرتجع', EXPENSE: 'مصروف', OPENING: 'رصيد افتتاحي', ADJUSTMENT: 'تسوية',
}

interface OperationsListProps {
  entries: JournalEntryOut[]
  loading: boolean
}

export function OperationsList({ entries, loading }: OperationsListProps) {
  const [expandedId, setExpandedId] = useState<number | null>(null)

  return (
    <aside className="journal-col journal-col-left">
      <div className="card-title" style={{ marginBottom: 10 }}>عمليات اليوم</div>
      {loading && <p className="text-muted">...جارٍ التحميل</p>}
      {!loading && entries.length === 0 && <p className="text-muted" style={{ fontSize: 13 }}>لا عمليات اليوم بعد</p>}
      <div className="today-ops-list">
        {entries.map((entry) => (
          <div key={entry.id} className="today-op-row">
            <button type="button" className="today-op-summary" onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}>
              <div>
                <div className="today-op-type">{OP_LABELS[entry.operation_type] ?? entry.operation_type}</div>
                <div className="text-muted" style={{ fontSize: 12 }}>{entry.client_name_ar ?? entry.entry_no}</div>
              </div>
              <div className="today-op-actions">
                {entry.chain_ref && <span className="badge badge-chain">{entry.chain_ref}</span>}
                <Eye size={16} strokeWidth={1.9} />
              </div>
            </button>
            {expandedId === entry.id && (
              <div className="today-op-detail">
                <div className="num text-muted" style={{ fontSize: 12 }}>{entry.entry_no}</div>
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
              </div>
            )}
          </div>
        ))}
      </div>
    </aside>
  )
}
