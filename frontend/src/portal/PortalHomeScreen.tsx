import { useEffect, useMemo, useState } from 'react'
import { RefreshCw, Printer } from 'lucide-react'
import Decimal from 'decimal.js'
import { api } from '../api/client'
import type { ClientBalance, Currency, Location, PortalMeResponse, StatementResponse } from '../api/types'
import { CurrencyBadge } from '../components/CurrencyBadge'
import { LogoMark } from '../components/LogoMark'
import './PortalHomeScreen.css'

interface PortalHomeScreenProps {
  me: PortalMeResponse
  onLogout: () => Promise<void>
}

interface CurrencyGroup {
  currency_code: string
  total: Decimal
  rows: ClientBalance[]
}

export function PortalHomeScreen({ me, onLogout }: PortalHomeScreenProps) {
  const [currencies, setCurrencies] = useState<Currency[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [balances, setBalances] = useState<ClientBalance[] | null>(null)
  const [selected, setSelected] = useState<{ currency: string; location: string } | null>(null)
  const [statement, setStatement] = useState<StatementResponse | null>(null)
  const [loading, setLoading] = useState(true)

  async function loadAll() {
    setLoading(true)
    const [c, l, b] = await Promise.all([
      api.get<Currency[]>('/portal/currencies'),
      api.get<Location[]>('/portal/locations'),
      api.get<ClientBalance[]>('/portal/balances'),
    ])
    setCurrencies(c)
    setLocations(l)
    setBalances(b)
    setLoading(false)
  }

  useEffect(() => {
    void loadAll()
  }, [])

  const groups: CurrencyGroup[] = useMemo(() => {
    if (!balances) return []
    const map = new Map<string, CurrencyGroup>()
    for (const row of balances) {
      const g = map.get(row.currency_code) ?? { currency_code: row.currency_code, total: new Decimal(0), rows: [] }
      g.total = g.total.plus(row.balance)
      g.rows.push(row)
      map.set(row.currency_code, g)
    }
    return [...map.values()]
  }, [balances])

  useEffect(() => {
    if (!selected && groups.length > 0 && groups[0].rows.length > 0) {
      setSelected({ currency: groups[0].rows[0].currency_code, location: groups[0].rows[0].location_code ?? '' })
    }
  }, [groups, selected])

  useEffect(() => {
    if (!selected || !selected.location) {
      setStatement(null)
      return
    }
    void api
      .get<StatementResponse>(`/portal/statement?currency=${selected.currency}&location=${selected.location}`)
      .then(setStatement)
  }, [selected])

  function decimalsFor(code: string): number {
    return currencies.find((c) => c.code === code)?.decimals ?? 2
  }
  function locationName(code: string | null): string {
    return locations.find((l) => l.code === code)?.name_ar ?? code ?? '—'
  }

  return (
    <div className="portal-home">
      <header className="portal-topbar">
        <div className="portal-topbar-brand">
          <div className="portal-topbar-logo"><LogoMark size={22} /></div>
          <div>
            <div className="portal-topbar-name">{me.name_ar}</div>
            <div className="portal-topbar-code num">{me.code}</div>
          </div>
        </div>
        <button type="button" className="btn-text" onClick={() => void onLogout()}>خروج</button>
      </header>

      <main className="portal-main">
        {loading && <p className="text-muted">...جارٍ التحميل</p>}

        {!loading && groups.length === 0 && <p className="text-muted">لا أرصدة مسجَّلة بعد</p>}

        <div className="portal-balance-cards">
          {groups.map((g) => (
            <div className="card portal-balance-card" key={g.currency_code}>
              <div className="portal-balance-card-top">
                <CurrencyBadge code={g.currency_code} />
                <span className={`num portal-balance-total ${g.total.lt(0) ? 'money-negative' : ''}`}>
                  {g.total.toFixed(decimalsFor(g.currency_code))}
                </span>
              </div>
              <div className="portal-balance-locations">
                {g.rows.map((r) => (
                  <button
                    key={r.account_code}
                    type="button"
                    className={`portal-location-row${selected?.currency === r.currency_code && selected?.location === r.location_code ? ' is-active' : ''}`}
                    onClick={() => setSelected({ currency: r.currency_code, location: r.location_code ?? '' })}
                  >
                    <span>{locationName(r.location_code)}</span>
                    <span className={`num ${new Decimal(r.balance).lt(0) ? 'money-negative' : ''}`}>
                      {new Decimal(r.balance).toFixed(decimalsFor(r.currency_code))}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        {selected && (
          <div className="card portal-statement-card">
            <div className="portal-statement-header">
              <span className="card-title">كشف الحساب — {locationName(selected.location)}</span>
              <div className="portal-statement-actions">
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadAll()} aria-label="تحديث">
                  <RefreshCw size={14} strokeWidth={1.9} />
                </button>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => window.print()} aria-label="طباعة">
                  <Printer size={14} strokeWidth={1.9} />
                </button>
              </div>
            </div>
            {!statement && <p className="text-muted">...جارٍ التحميل</p>}
            {statement && (
              <div className="portal-tx-list">
                {statement.rows.length === 0 && <p className="text-muted" style={{ fontSize: 13 }}>لا حركة في هذا الحساب بعد</p>}
                {statement.rows.map((r) => {
                  const isDebit = Number(r.debit) !== 0
                  const amount = isDebit ? r.debit : r.credit
                  return (
                    <div className="portal-tx-row" key={r.entry_id}>
                      <div>
                        <div className="portal-tx-desc">{r.description ?? r.operation_type}</div>
                        <div className="num text-muted portal-tx-date">{r.entry_date}</div>
                      </div>
                      <span className={`num ${isDebit ? 'money-negative' : 'money-positive'}`}>
                        {isDebit ? '−' : '+'}{new Decimal(amount).toFixed(decimalsFor(selected.currency))}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        <div className="portal-bottom-buttons">
          <button type="button" className="btn btn-primary-dark btn-lg" onClick={() => window.print()}>
            طباعة كشف PDF
          </button>
          <button type="button" className="btn btn-secondary btn-lg" onClick={() => void loadAll()}>
            تحديث
          </button>
        </div>
      </main>
    </div>
  )
}
