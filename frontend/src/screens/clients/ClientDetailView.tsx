import { useEffect, useMemo, useState } from 'react'
import Decimal from 'decimal.js'
import { ArrowRight, PenLine } from 'lucide-react'
import { api, ApiError } from '../../api/client'
import type { ClientDetail, StatementResponse } from '../../api/types'
import { CurrencyBadge } from '../../components/CurrencyBadge'
import { useReferenceData } from '../../hooks/useReferenceData'
import { BeneficiariesPanel } from './BeneficiariesPanel'

interface ClientDetailViewProps {
  clientId: number
  currentUserRole: 'ADMIN' | 'ACCOUNTANT'
  onBack: () => void
}

export function ClientDetailView({ clientId, currentUserRole, onBack }: ClientDetailViewProps) {
  const { currencies, locationsForCurrency } = useReferenceData()
  const [detail, setDetail] = useState<ClientDetail | null>(null)
  const [activeCcy, setActiveCcy] = useState('')
  const [activeLocation, setActiveLocation] = useState('')
  const [statement, setStatement] = useState<StatementResponse | null>(null)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const [editPhone, setEditPhone] = useState('')

  async function reloadDetail() {
    const data = await api.get<ClientDetail>(`/clients/${clientId}`)
    setDetail(data)
    setEditName(data.name_ar)
    setEditPhone(data.phone ?? '')
    if (!activeCcy && currencies.length) setActiveCcy(currencies[0].code)
  }

  useEffect(() => {
    void reloadDetail()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId, currencies.length])

  const currentLocations = useMemo(() => locationsForCurrency(activeCcy), [activeCcy, locationsForCurrency])

  useEffect(() => {
    if (currentLocations.length && !currentLocations.some((l) => l.code === activeLocation)) {
      setActiveLocation(currentLocations[0].code)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCcy, currentLocations])

  async function loadStatement() {
    if (!activeCcy || !activeLocation) return
    const params = new URLSearchParams({ currency: activeCcy, location: activeLocation })
    if (dateFrom) params.set('from', dateFrom)
    if (dateTo) params.set('to', dateTo)
    const data = await api.get<StatementResponse>(`/clients/${clientId}/statement?${params.toString()}`)
    setStatement(data)
  }

  useEffect(() => {
    void loadStatement()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCcy, activeLocation])

  async function saveEdit() {
    const updated = await api.patch<ClientDetail>(`/clients/${clientId}`, { name_ar: editName, phone: editPhone })
    setDetail(updated)
    setEditing(false)
  }

  async function setCreditAllowed(value: boolean) {
    await api.patch(`/clients/${clientId}/credit-allowed`, { credit_allowed: value })
    await reloadDetail()
  }

  if (!detail) return <p className="text-muted">...جارٍ التحميل</p>

  const ccy = currencies.find((c) => c.code === activeCcy)
  const decimals = ccy?.decimals ?? 2
  const totalForCcy = detail.balances
    .filter((b) => b.currency_code === activeCcy)
    .reduce((sum, b) => sum.plus(b.balance), new Decimal(0))
  const limitForCcy = detail.credit_limits.find((l) => l.currency_code === activeCcy)

  return (
    <div className="clients-screen">
      <button type="button" className="btn-text" style={{ marginBottom: 12 }} onClick={onBack}>
        <ArrowRight size={16} /> رجوع لقائمة العملاء
      </button>

      <div className="card" style={{ marginBottom: 16 }}>
        {!editing ? (
          <div className="client-detail-header">
            <div>
              <h2 className="screen-title" style={{ fontSize: 20 }}>{detail.name_ar}</h2>
              <div className="num text-muted">{detail.code}{detail.phone ? ` · ${detail.phone}` : ''}</div>
            </div>
            <div className="op-row" style={{ gap: 8 }}>
              <a href={`/documents/balance-card/${clientId}.png`} target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">
                بطاقة الرصيد
              </a>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditing(true)}>
                <PenLine size={14} /> تعديل
              </button>
            </div>
          </div>
        ) : (
          <div className="op-row">
            <div className="field"><label className="field-label">الاسم</label>
              <input value={editName} onChange={(e) => setEditName(e.target.value)} /></div>
            <div className="field"><label className="field-label">الهاتف</label>
              <input value={editPhone} onChange={(e) => setEditPhone(e.target.value)} /></div>
            <button type="button" className="btn btn-primary" onClick={() => void saveEdit()}>حفظ</button>
            <button type="button" className="btn btn-secondary" onClick={() => setEditing(false)}>إلغاء</button>
          </div>
        )}

        {currentUserRole === 'ADMIN' && (
          <div className="client-credit-admin">
            <label className="field-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input type="checkbox" checked={detail.credit_allowed} onChange={(e) => void setCreditAllowed(e.target.checked)} />
              يسمح بائتمان (رصيد سالب) لهذا العميل
            </label>
          </div>
        )}
        {!detail.credit_allowed && <span className="badge badge-status-reversed">بلا ائتمان مسموح</span>}
      </div>

      <div className="op-tabs" style={{ marginBottom: 12 }}>
        {currencies.map((c) => (
          <button
            key={c.code} type="button" className={`op-tab${activeCcy === c.code ? ' is-active' : ''}`}
            onClick={() => setActiveCcy(c.code)}
          >
            {c.name_ar}
          </button>
        ))}
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="client-balance-total">
          <span>الإجمالي</span>
          <span className={`num ${totalForCcy.lt(0) ? 'money-negative' : ''}`} style={{ fontSize: 22, fontWeight: 700 }}>
            {totalForCcy.toFixed(decimals)}
          </span>
          {ccy && <CurrencyBadge code={ccy.code} />}
        </div>
        {currentUserRole === 'ADMIN' && (
          <CreditLimitEditor
            clientId={clientId} currency={activeCcy} current={limitForCcy?.limit_amount} decimals={decimals}
            onSaved={reloadDetail}
          />
        )}
        <div className="client-balances" style={{ marginTop: 12 }}>
          {currentLocations.map((loc) => {
            const b = detail.balances.find((x) => x.currency_code === activeCcy && x.location_code === loc.code)
            return (
              <div className="client-balance-row" key={loc.code}>
                <span className="location-label">{loc.name_ar}</span>
                <span className={`num balance-amount ${b && new Decimal(b.balance).lt(0) ? 'money-negative' : ''}`}>
                  {b ? new Decimal(b.balance).toFixed(decimals) : (0).toFixed(decimals)}
                </span>
              </div>
            )
          })}
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="clients-header" style={{ marginBottom: 12 }}>
          <div className="card-title">كشف الحساب — {ccy?.name_ar}</div>
          <div className="op-row" style={{ gap: 8 }}>
            {currentLocations.length > 1 && (
              <select value={activeLocation} onChange={(e) => setActiveLocation(e.target.value)}>
                {currentLocations.map((l) => <option key={l.code} value={l.code}>{l.name_ar}</option>)}
              </select>
            )}
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
            <span className="text-muted">إلى</span>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadStatement()}>تصفية</button>
            <a
              href={`/documents/statement/client/${clientId}.pdf?currency=${activeCcy}&location=${activeLocation}${dateFrom ? `&date_from=${dateFrom}` : ''}${dateTo ? `&date_to=${dateTo}` : ''}`}
              target="_blank" rel="noreferrer" className="btn-text"
            >
              طباعة PDF
            </a>
          </div>
        </div>
        {statement && (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>التاريخ</th><th>القيد</th><th>العملية</th><th>البيان</th>
                  <th>مدين</th><th>دائن</th><th>الرصيد المتحرك</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td colSpan={6} className="text-muted">الرصيد الافتتاحي</td>
                  <td className="num">{new Decimal(statement.opening_balance).toFixed(decimals)}</td>
                </tr>
                {statement.rows.map((r) => (
                  <tr key={r.entry_id}>
                    <td className="num">{r.entry_date}</td>
                    <td className="num">{r.entry_no}</td>
                    <td>{r.operation_type}</td>
                    <td>{r.description}</td>
                    <td className="num">{new Decimal(r.debit).toFixed(decimals)}</td>
                    <td className="num">{new Decimal(r.credit).toFixed(decimals)}</td>
                    <td className="num" style={{ fontWeight: 600 }}>{new Decimal(r.running_balance).toFixed(decimals)}</td>
                  </tr>
                ))}
                {statement.rows.length === 0 && (
                  <tr><td colSpan={7} className="text-muted">لا حركة في هذا النطاق</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <BeneficiariesPanel clientId={clientId} currencies={currencies} />
    </div>
  )
}

function CreditLimitEditor({
  clientId, currency, current, decimals, onSaved,
}: { clientId: number; currency: string; current?: string; decimals: number; onSaved: () => Promise<void> }) {
  const [value, setValue] = useState(current ? new Decimal(current).toFixed(decimals) : '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => setValue(current ? new Decimal(current).toFixed(decimals) : ''), [current, decimals])

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await api.put(`/clients/${clientId}/credit-limits/${currency}`, { limit_amount: value || '0' })
      await onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر حفظ حد الائتمان')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="op-row" style={{ marginTop: 12, alignItems: 'flex-end' }}>
      <div className="field" style={{ maxWidth: 200 }}>
        <label className="field-label">حد الائتمان بعملة {currency}</label>
        <input className="num" value={value} onChange={(e) => setValue(e.target.value)} />
      </div>
      <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void save()}>حفظ الحد</button>
      {error && <span style={{ color: 'var(--money-out-text)', fontSize: 12 }}>{error}</span>}
    </div>
  )
}
