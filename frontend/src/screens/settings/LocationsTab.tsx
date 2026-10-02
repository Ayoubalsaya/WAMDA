import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { ClientCurrencyLocationRow, LocationAdminRow } from '../../api/types'
import { useReferenceData } from '../../hooks/useReferenceData'
import { useFormErrors } from '../../hooks/useFormErrors'

function CreateLocationForm({ onCreated }: { onCreated: () => void }) {
  const [code, setCode] = useState('')
  const [nameAr, setNameAr] = useState('')
  const [country, setCountry] = useState('')
  const [busy, setBusy] = useState(false)
  const { ref: formRef, error, setError, report, portals } = useFormErrors({ code: 'الكود', name_ar: 'الاسم', country: 'الدولة' })

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post('/settings/locations', { code, name_ar: nameAr, country })
      setCode(''); setNameAr(''); setCountry('')
      onCreated()
    } catch (err) {
      report(err, 'تعذّر إنشاء الموقع')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form ref={formRef} onSubmit={submit} className="op-row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 16, alignItems: 'flex-end' }}>
      <div className="field" style={{ maxWidth: 110 }}>
        <label className="field-label" htmlFor="cl-code">الكود</label>
        <input id="cl-code" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} maxLength={32} required />
      </div>
      <div className="field"><label className="field-label" htmlFor="cl-name">الاسم</label><input id="cl-name" value={nameAr} onChange={(e) => setNameAr(e.target.value)} required /></div>
      <div className="field"><label className="field-label" htmlFor="cl-country">الدولة</label><input id="cl-country" value={country} onChange={(e) => setCountry(e.target.value)} required /></div>
      <button type="submit" className="btn btn-primary" disabled={busy}>+ موقع جديد</button>
      {error && <div className="alert alert-critical" style={{ width: '100%' }}>{error}</div>}
      {portals}
    </form>
  )
}

function LocationEditRow({ row, onSaved, onCancel }: { row: LocationAdminRow; onSaved: () => void; onCancel: () => void }) {
  const [nameAr, setNameAr] = useState(row.name_ar)
  const [country, setCountry] = useState(row.country)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await api.patch(`/settings/locations/${row.code}`, { name_ar: nameAr, country })
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر الحفظ')
    } finally {
      setBusy(false)
    }
  }

  return (
    <tr>
      <td className="num text-muted">{row.code}</td>
      <td><input value={nameAr} onChange={(e) => setNameAr(e.target.value)} style={{ width: '100%' }} /></td>
      <td><input value={country} onChange={(e) => setCountry(e.target.value)} style={{ width: '100%' }} /></td>
      <td><span className={`badge ${row.is_active ? 'badge-status-posted' : 'badge-status-reversed'}`}>{row.is_active ? 'نشط' : 'معطَّل'}</span></td>
      <td>
        <div style={{ display: 'flex', gap: 6 }}>
          <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void save()}>حفظ</button>
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={onCancel}>إلغاء</button>
        </div>
        {error && <div className="alert alert-critical" style={{ marginTop: 6, fontSize: 'var(--fs-xs)' }}>{error}</div>}
      </td>
    </tr>
  )
}

function LocationDisplayRow({ row, onEdit, onToggled }: { row: LocationAdminRow; onEdit: () => void; onToggled: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function toggle() {
    setBusy(true)
    setError(null)
    try {
      await api.patch(`/settings/locations/${row.code}`, { is_active: !row.is_active })
      onToggled()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر تغيير الحالة')
    } finally {
      setBusy(false)
    }
  }

  return (
    <tr>
      <td className="num text-muted">{row.code}</td>
      <td>{row.name_ar}</td>
      <td>{row.country}</td>
      <td><span className={`badge ${row.is_active ? 'badge-status-posted' : 'badge-status-reversed'}`}>{row.is_active ? 'نشط' : 'معطَّل'}</span></td>
      <td>
        <div style={{ display: 'flex', gap: 6 }}>
          <button type="button" className="btn btn-secondary btn-sm" onClick={onEdit}>تعديل</button>
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void toggle()}>
            {row.is_active ? 'تعطيل' : 'تفعيل'}
          </button>
        </div>
        {error && <div className="alert alert-critical" style={{ marginTop: 6, fontSize: 'var(--fs-xs)' }}>{error}</div>}
      </td>
    </tr>
  )
}

function AddClientCurrencyLocationForm({ onAdded }: { onAdded: () => void }) {
  const { currencies, locations } = useReferenceData()
  const [currencyCode, setCurrencyCode] = useState('')
  const [locationCode, setLocationCode] = useState('')
  const [busy, setBusy] = useState(false)
  const { ref: formRef, error, setError, report, portals } = useFormErrors({ currency_code: 'العملة', location_code: 'الموقع' })

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!currencyCode || !locationCode) return
    setBusy(true)
    setError(null)
    try {
      await api.post('/settings/client-currency-locations', { currency_code: currencyCode, location_code: locationCode })
      setCurrencyCode(''); setLocationCode('')
      onAdded()
    } catch (err) {
      report(err, 'تعذّر إضافة التركيبة')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form ref={formRef} onSubmit={submit} className="op-row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 12, alignItems: 'flex-end' }}>
      <div className="field">
        <label className="field-label" htmlFor="ccl-ccy">العملة</label>
        <select id="ccl-ccy" value={currencyCode} onChange={(e) => setCurrencyCode(e.target.value)} required>
          <option value="" disabled>اختر عملة</option>
          {currencies.map((c) => <option key={c.code} value={c.code}>{c.name_ar}</option>)}
        </select>
      </div>
      <div className="field">
        <label className="field-label" htmlFor="ccl-loc">الموقع</label>
        <select id="ccl-loc" value={locationCode} onChange={(e) => setLocationCode(e.target.value)} required>
          <option value="" disabled>اختر موقعاً</option>
          {locations.map((l) => <option key={l.code} value={l.code}>{l.name_ar}</option>)}
        </select>
      </div>
      <button type="submit" className="btn btn-primary" disabled={busy}>+ سماح تركيبة</button>
      {error && <div className="alert alert-critical" style={{ width: '100%' }}>{error}</div>}
      {portals}
    </form>
  )
}

// عملة جديدة تُبني لها شجرة حسابات الشركة فوراً عند الإنشاء (CurrenciesTab)
// لكن حسابات العملاء 2100-* تظل مرفوضة (InvalidClientLocationError) لأي
// موقع حتى تُضاف تركيبة صريحة هنا — بلا هذا لا يمكن لأي عميل قبض/صرافة
// بعملة جديدة في أي مكان (٢٠٢٦-٠٩-٢٥، سدّ فجوة).
function ClientCurrencyLocationsSection() {
  const [rows, setRows] = useState<ClientCurrencyLocationRow[] | null>(null)

  async function reload() {
    const data = await api.get<ClientCurrencyLocationRow[]>('/settings/client-currency-locations')
    setRows(data)
  }

  useEffect(() => { void reload() }, [])

  return (
    <div style={{ marginTop: 28 }}>
      <h3 className="card-title">تركيبات العملة والموقع المسموحة لحسابات العملاء</h3>
      <p className="text-muted" style={{ marginTop: -4, marginBottom: 12, fontSize: 'var(--fs-sm)' }}>
        عميل لا يمكنه القبض أو الصرافة بعملة في موقع إلا بعد إضافة التركيبة هنا — لا حذف، إضافة فقط.
      </p>
      <AddClientCurrencyLocationForm onAdded={() => void reload()} />
      {!rows ? <p className="text-muted">...جارٍ التحميل</p> : (
        <table className="data-table">
          <thead><tr><th>العملة</th><th>الموقع</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.currency_code}-${r.location_code}`}>
                <td className="num">{r.currency_code}</td>
                <td>{r.location_code}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={2} className="text-muted">لا تركيبات مسجَّلة بعد</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  )
}

export function LocationsTab() {
  const [rows, setRows] = useState<LocationAdminRow[] | null>(null)
  const [editingCode, setEditingCode] = useState<string | null>(null)

  async function reload() {
    const data = await api.get<LocationAdminRow[]>('/settings/locations')
    setRows(data)
  }

  useEffect(() => { void reload() }, [])

  return (
    <>
      <CreateLocationForm onCreated={() => void reload()} />
      {!rows ? <p className="text-muted">...جارٍ التحميل</p> : (
        <table className="data-table">
          <thead><tr><th>الكود</th><th>الاسم</th><th>الدولة</th><th>الحالة</th><th></th></tr></thead>
          <tbody>
            {rows.map((r) => r.code === editingCode ? (
              <LocationEditRow
                key={r.code} row={r}
                onSaved={() => { setEditingCode(null); void reload() }}
                onCancel={() => setEditingCode(null)}
              />
            ) : (
              <LocationDisplayRow
                key={r.code} row={r}
                onEdit={() => setEditingCode(r.code)}
                onToggled={() => void reload()}
              />
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="text-muted">لا مواقع مسجَّلة بعد</td></tr>}
          </tbody>
        </table>
      )}
      <ClientCurrencyLocationsSection />
    </>
  )
}
