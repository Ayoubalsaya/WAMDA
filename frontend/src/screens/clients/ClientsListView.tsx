import { useEffect, useState } from 'react'
import Decimal from 'decimal.js'
import { Plus } from 'lucide-react'
import { api } from '../../api/client'
import type { ClientListRow, Currency } from '../../api/types'
import { useReferenceData } from '../../hooks/useReferenceData'

interface ClientsListViewProps {
  onSelect: (clientId: number) => void
  onCreate: () => void
}

function formatAmount(value: string, currency?: Currency): string {
  return new Decimal(value).toFixed(currency?.decimals ?? 2)
}

export function ClientsListView({ onSelect, onCreate }: ClientsListViewProps) {
  const { currencies } = useReferenceData()
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<ClientListRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    const timer = setTimeout(async () => {
      const data = await api.get<ClientListRow[]>(`/clients${q ? `?q=${encodeURIComponent(q)}` : ''}`)
      if (!cancelled) {
        setRows(data)
        setLoading(false)
      }
    }, 200)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [q])

  const currencyByCode = (code: string) => currencies.find((c) => c.code === code)

  return (
    <div className="clients-screen">
      <div className="clients-header">
        <h2 className="screen-title">العملاء</h2>
        <button type="button" className="btn btn-primary" onClick={onCreate}>
          <Plus size={18} strokeWidth={2} /> عميل جديد
        </button>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <input
          value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="بحث ذكي — اسم أو كود أو هاتف..." style={{ maxWidth: 380 }}
        />
      </div>

      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>العميل</th>
              {currencies.map((c) => <th key={c.code}>{c.name_ar}</th>)}
              <th>آخر حركة</th>
            </tr>
          </thead>
          <tbody>
            {!loading && rows.length === 0 && (
              <tr><td colSpan={currencies.length + 2} className="text-muted">لا عملاء مطابقون</td></tr>
            )}
            {rows.map((row) => (
              <tr key={row.id} className="clients-row" onClick={() => onSelect(row.id)}>
                <td>
                  <div style={{ fontWeight: 600 }}>{row.name_ar}</div>
                  <div className="num text-muted" style={{ fontSize: 'var(--fs-xs)' }}>{row.code}</div>
                </td>
                {currencies.map((c) => {
                  const balance = row.balances.find((b) => b.currency_code === c.code)
                  const limit = row.credit_limits.find((l) => l.currency_code === c.code)
                  return (
                    <td key={c.code} className="col-amount">
                      {balance ? (
                        <>
                          <div className={`num ${new Decimal(balance.balance).lt(0) ? 'money-negative' : ''}`}>
                            {formatAmount(balance.balance, currencyByCode(c.code))}
                          </div>
                          {limit && limit.mode === 'LIMIT' && limit.limit_amount !== null && (
                            <div className="num text-muted" style={{ fontSize: 'var(--fs-2xs)' }}>
                              حد {formatAmount(limit.limit_amount, currencyByCode(c.code))}
                            </div>
                          )}
                          {limit && limit.mode === 'UNLIMITED' && (
                            <div className="text-muted" style={{ fontSize: 'var(--fs-2xs)' }}>بلا سقف</div>
                          )}
                        </>
                      ) : <span className="text-muted">—</span>}
                    </td>
                  )
                })}
                <td className="num">{row.last_activity ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
