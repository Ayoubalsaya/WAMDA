import { useEffect, useState } from 'react'
import Decimal from 'decimal.js'
import { Search, User, X } from 'lucide-react'
import { api } from '../../api/client'
import type { ClientBalance, ClientSearchResult } from '../../api/types'
import { CurrencyBadge } from '../../components/CurrencyBadge'
import { useReferenceData } from '../../hooks/useReferenceData'
import './journal-design.css'

interface ClientPanelProps {
  selected: ClientSearchResult | null
  onSelect: (client: ClientSearchResult | null) => void
  refreshToken?: number
}

export function ClientPanel({ selected, onSelect, refreshToken }: ClientPanelProps) {
  const { currencies } = useReferenceData()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<ClientSearchResult[]>([])
  const [balances, setBalances] = useState<ClientBalance[]>([])

  function formatBalance(b: ClientBalance): string {
    const decimals = currencies.find((c) => c.code === b.currency_code)?.decimals ?? 2
    return new Decimal(b.balance).toFixed(decimals)
  }

  useEffect(() => {
    if (!query.trim()) {
      setResults([])
      return
    }
    let cancelled = false
    const timer = setTimeout(async () => {
      const rows = await api.get<ClientSearchResult[]>(`/clients/search?q=${encodeURIComponent(query)}`)
      if (!cancelled) setResults(rows)
    }, 200)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [query])

  useEffect(() => {
    if (!selected) {
      setBalances([])
      return
    }
    let cancelled = false
    void api.get<ClientBalance[]>(`/clients/${selected.id}/balances`).then((rows) => {
      if (!cancelled) setBalances(rows)
    })
    return () => {
      cancelled = true
    }
  }, [selected, refreshToken])

  return (
    <aside className="journal-col journal-col-right">
      <section className="jr-panel">
        <div className="dock-heading">
          <div>
            <span className="panel-kicker">٠١ / السياق</span>
            <h3>عدسة العميل</h3>
          </div>
          {selected && (
            <button type="button" className="mini-icon" title="مسح العميل" onClick={() => onSelect(null)}>
              <X size={18} strokeWidth={2} />
            </button>
          )}
        </div>

        <label className="client-search-box" htmlFor="client-search">
          <Search size={16} strokeWidth={2} aria-hidden="true" />
          <input
            id="client-search"
            value={selected ? selected.name_ar : query}
            onChange={(e) => {
              onSelect(null)
              setQuery(e.target.value)
            }}
            placeholder="اسم أو كود أو هاتف..."
          />
        </label>
        {results.length > 0 && !selected && (
          <div className="client-search-results">
            {results.map((r) => (
              <button
                key={r.id}
                type="button"
                className="client-result"
                onClick={() => {
                  onSelect(r)
                  setResults([])
                  setQuery('')
                }}
              >
                <span>{r.name_ar}</span>
                <span className="num text-muted">{r.code}</span>
              </button>
            ))}
          </div>
        )}

        {!selected && (
          <div className="empty-client">
            <span className="empty-client-icon"><User size={20} strokeWidth={2} /></span>
            <strong>لا يوجد عميل محدد</strong>
            <span>اختيار العميل يجعل المعاينة والرصيد أكثر دقة.</span>
          </div>
        )}

        {selected && (
          <div className="client-profile" style={{ marginTop: 12 }}>
            <span className="client-avatar">{selected.name_ar.slice(0, 1)}</span>
            <div className="client-profile-copy">
              <strong>{selected.name_ar}</strong>
              <small className="num">{selected.code}</small>
              {!selected.credit_allowed && (
                <div className="client-tags">
                  <span className="badge badge-status-reversed">بلا ائتمان مسموح</span>
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {selected && (
        <section className="jr-panel balance-panel">
          <div className="dock-heading">
            <div>
              <span className="panel-kicker">رصيد حي</span>
              <h3>لوحة العميل</h3>
            </div>
          </div>
          {balances.length === 0 ? (
            <p className="balance-empty">لا أرصدة بعد</p>
          ) : (
            <div className="balance-list">
              {balances.map((b) => (
                <div key={b.account_code}>
                  <CurrencyBadge code={b.currency_code} />
                  <span className="balance-place">{b.location_code ?? '—'}</span>
                  <span className="num balance-figure">{formatBalance(b)}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </aside>
  )
}
