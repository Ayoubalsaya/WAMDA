import { useEffect, useState } from 'react'
import Decimal from 'decimal.js'
import { api } from '../../api/client'
import type { ClientBalance, ClientSearchResult } from '../../api/types'
import { CurrencyBadge } from '../../components/CurrencyBadge'
import { useReferenceData } from '../../hooks/useReferenceData'

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
      <div className="card">
        <label className="field-label" htmlFor="client-search">العميل</label>
        <input
          id="client-search"
          value={selected ? selected.name_ar : query}
          onChange={(e) => {
            onSelect(null)
            setQuery(e.target.value)
          }}
          placeholder="اسم أو كود أو هاتف..."
        />
        {results.length > 0 && !selected && (
          <div className="client-search-results">
            {results.map((r) => (
              <button
                key={r.id}
                type="button"
                className="client-search-row"
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
      </div>

      {selected && (
        <div className="card client-selected-card">
          <div className="client-avatar">{selected.name_ar.slice(0, 1)}</div>
          <div className="card-title">{selected.name_ar}</div>
          <div className="num text-muted">{selected.code}</div>
          {!selected.credit_allowed && (
            <span className="badge badge-status-reversed" style={{ marginTop: 6 }}>بلا ائتمان مسموح</span>
          )}
          <div className="client-balances">
            {balances.length === 0 && <p className="text-muted" style={{ fontSize: 13 }}>لا أرصدة بعد</p>}
            {balances.map((b) => (
              <div className="client-balance-row" key={b.account_code}>
                <CurrencyBadge code={b.currency_code} />
                <span className="location-label">{b.location_code ?? '—'}</span>
                <span className="num balance-amount">{formatBalance(b)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </aside>
  )
}
