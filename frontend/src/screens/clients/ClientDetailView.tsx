import { useEffect, useMemo, useState } from 'react'
import Decimal from 'decimal.js'
import { ArrowRight, PenLine } from 'lucide-react'
import { api } from '../../api/client'
import type { ClientDetail, CreditLimitOut, CreditMode, StatementResponse } from '../../api/types'
import { CreditControls, CreditStatusBadge } from '../../components/CreditControls'
import { BalanceCardCopyButton } from '../../components/BalanceCardCopyButton'
import { CurrencyBadge } from '../../components/CurrencyBadge'
import { DecimalError, DecimalInput } from '../../components/DecimalInput'
import { decimalInputError } from '../../lib/decimalInput'
import { EditedBadge, EntryActionsBar } from '../../components/EntryActions'
import { SegmentedTabs } from '../../components/SegmentedTabs'
import { useReferenceData } from '../../hooks/useReferenceData'
import { ClientPortalSection } from './ClientPortalSection'
import { useFormErrors } from '../../hooks/useFormErrors'

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
  const [includeReversed, setIncludeReversed] = useState(false)

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
    if (includeReversed) params.set('include_reversed', 'true')
    const data = await api.get<StatementResponse>(`/clients/${clientId}/statement?${params.toString()}`)
    setStatement(data)
  }

  useEffect(() => {
    void loadStatement()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCcy, activeLocation, includeReversed])

  async function saveEdit() {
    const updated = await api.patch<ClientDetail>(`/clients/${clientId}`, { name_ar: editName, phone: editPhone })
    setDetail(updated)
    setEditing(false)
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
              <h2 className="screen-title" style={{ fontSize: 'var(--fs-h3)' }}>{detail.name_ar}</h2>
              <div className="num text-muted">{detail.code}{detail.phone ? ` · ${detail.phone}` : ''}</div>
            </div>
            <div className="op-row" style={{ gap: 8 }}>
              <a href={`/documents/balance-card/${clientId}.png`} target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">
                بطاقة الرصيد
              </a>
              <BalanceCardCopyButton src={`/documents/balance-card/${clientId}.png`} />
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

        <div className="client-credit-admin" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <CreditStatusBadge status={detail.credit_status} />
          {currentUserRole === 'ADMIN' && (
            <CreditControls clientId={clientId} status={detail.credit_status} onChanged={() => void reloadDetail()} />
          )}
        </div>
      </div>

      {currentUserRole === 'ADMIN' && (
        <ClientPortalSection clientId={clientId} clientName={detail.name_ar} clientPhone={detail.phone} />
      )}

      <div style={{ marginBottom: 12 }}>
        <SegmentedTabs
          variant="dock" ariaLabel="عملة كشف الحساب" value={activeCcy} onChange={setActiveCcy}
          items={currencies.map((c) => ({ id: c.code, label: c.name_ar }))}
        />
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="client-balance-total">
          <span>الإجمالي</span>
          <span className={`num ${totalForCcy.lt(0) ? 'money-negative' : ''}`} style={{ fontSize: 'var(--fs-h3)', fontWeight: 700 }}>
            {totalForCcy.toFixed(decimals)}
          </span>
          {ccy && <CurrencyBadge code={ccy.code} />}
        </div>
        {currentUserRole === 'ADMIN' && (
          <CreditLimitEditor
            clientId={clientId} currency={activeCcy} setting={limitForCcy} decimals={decimals}
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
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 'var(--fs-xs)', cursor: 'pointer' }}>
              <input type="checkbox" checked={includeReversed} onChange={(e) => setIncludeReversed(e.target.checked)} />
              إظهار الملغاة
            </label>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadStatement()}>تصفية</button>
            <a
              href={`/documents/statement/client/${clientId}.pdf?currency=${activeCcy}&location=${activeLocation}${dateFrom ? `&date_from=${dateFrom}` : ''}${dateTo ? `&date_to=${dateTo}` : ''}`}
              target="_blank" rel="noreferrer" className="btn-text"
            >
              طباعة PDF
            </a>
            <a
              href={`/documents/statement/client/${clientId}.xlsx?currency=${activeCcy}&location=${activeLocation}${dateFrom ? `&date_from=${dateFrom}` : ''}${dateTo ? `&date_to=${dateTo}` : ''}`}
              target="_blank" rel="noreferrer" className="btn-text"
            >
              تنزيل Excel
            </a>
          </div>
        </div>
        {statement && (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>التاريخ</th><th>القيد</th><th>العملية</th><th>البيان</th><th>السعر</th>
                  <th>مدين</th><th>دائن</th><th>الرصيد المتحرك</th><th></th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td colSpan={7} className="text-muted">الرصيد الافتتاحي</td>
                  <td className="num">{new Decimal(statement.opening_balance).toFixed(decimals)}</td>
                  <td></td>
                </tr>
                {statement.rows.map((r) => (
                  <tr key={r.entry_id} style={r.status === 'REVERSED' ? { opacity: 0.55 } : undefined}>
                    <td className="num">{r.entry_date}</td>
                    <td className="num">{r.entry_no}</td>
                    <td style={r.status === 'REVERSED' ? { textDecoration: 'line-through' } : undefined}>{r.operation_type}</td>
                    <td>{r.description}{r.note && <div className="text-muted" style={{ fontSize: 'var(--fs-2xs)' }}>{r.note}</div>}</td>
                    <td className="num">{r.client_rate ?? '—'}</td>
                    <td className="num">{new Decimal(r.debit).toFixed(decimals)}</td>
                    <td className="num">{new Decimal(r.credit).toFixed(decimals)}</td>
                    <td className="num" style={{ fontWeight: 600 }}>{new Decimal(r.running_balance).toFixed(decimals)}</td>
                    <td style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      {r.status === 'REVERSED' && <span className="badge badge-status-reversed">ملغاة</span>}
                      {r.replaces_entry_id && <EditedBadge entryId={r.entry_id} />}
                      <EntryActionsBar
                        entry={{ id: r.entry_id, status: r.status, chain_ref: r.chain_ref, operation_type: r.operation_type, client_id: clientId }}
                        currentUserRole={currentUserRole} onChanged={() => void loadStatement()}
                      />
                    </td>
                  </tr>
                ))}
                {statement.rows.length === 0 && (
                  <tr><td colSpan={9} className="text-muted">لا حركة في هذا النطاق</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// لكل عملة على حدة، ثلاث حالات: بلا ائتمان · حد بمبلغ · بلا سقف (٢٠٢٦-١٠-٠٣). الحفظ يستبدل وضع هذه العملة فقط.
const MODE_LABEL: Record<CreditMode, string> = { NONE: 'بلا ائتمان', LIMIT: 'حد بمبلغ', UNLIMITED: 'بلا سقف' }

function CreditLimitEditor({
  clientId, currency, setting, decimals, onSaved,
}: { clientId: number; currency: string; setting?: CreditLimitOut; decimals: number; onSaved: () => Promise<void> }) {
  const current = setting?.limit_amount ?? undefined
  const [mode, setMode] = useState<CreditMode>(setting?.mode ?? 'NONE')
  const [value, setValue] = useState(current ? new Decimal(current).toFixed(decimals) : '')
  const [busy, setBusy] = useState(false)
  const { ref: formRef, error, setError, report, portals } = useFormErrors((key, server) => (key === 'limit_amount' ? `حد الائتمان بعملة ${currency}` : (server ?? 'الحقل')))

  useEffect(() => {
    setMode(setting?.mode ?? 'NONE')
    setValue(current ? new Decimal(current).toFixed(decimals) : '')
  }, [setting?.mode, current, decimals, currency])

  async function save() {
    if (mode === 'LIMIT') {
      const limitError = decimalInputError(value)
      if (limitError) {
        setError(`«حد الائتمان»: ${limitError}`)
        return
      }
    }
    setBusy(true)
    setError(null)
    try {
      await api.put(`/clients/${clientId}/credit-limits/${currency}`, mode === 'LIMIT' ? { mode, limit_amount: value || '0' } : { mode })
      await onSaved()
    } catch (err) {
      report(err, 'تعذّر حفظ حد الائتمان')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div ref={formRef} className="op-row" style={{ marginTop: 12, alignItems: 'flex-end', flexWrap: 'wrap' }} data-testid="credit-limit-editor">
      <div className="field">
        <span className="field-label">الائتمان بعملة {currency}</span>
        <div className="credit-mode-radios" role="radiogroup" aria-label={`الائتمان بعملة ${currency}`}>
          {(['NONE', 'LIMIT', 'UNLIMITED'] as CreditMode[]).map((m) => (
            <label key={m} className={`credit-mode-option${mode === m ? ' is-active' : ''}`}>
              <input type="radio" name={`credit-mode-${currency}`} checked={mode === m} onChange={() => { setMode(m); setError(null) }} />
              {MODE_LABEL[m]}
            </label>
          ))}
        </div>
      </div>
      {mode === 'LIMIT' && (
        <div className="field" style={{ maxWidth: 200 }}>
          <label className="field-label">حد الائتمان بعملة {currency}</label>
          {/* الفارغ يُحفَظ صفراً — placeholder ٠ كي يطابق المعروضُ المُرسَلَ */}
          <DecimalInput className="num" placeholder="0" value={value} onChange={(v) => { setValue(v); setError(null) }} />
          <DecimalError value={value} />
        </div>
      )}
      <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void save()}>حفظ الحد</button>
      {error && <span style={{ color: 'var(--money-out-text)', fontSize: 'var(--fs-xs)' }}>{error}</span>}
      {portals}
    </div>
  )
}
