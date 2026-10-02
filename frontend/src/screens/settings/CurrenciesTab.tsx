import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { CurrencyAdminRow } from '../../api/types'
import { useFormErrors } from '../../hooks/useFormErrors'

function CreateCurrencyForm({ onCreated }: { onCreated: () => void }) {
  const [code, setCode] = useState('')
  const [nameAr, setNameAr] = useState('')
  const [symbol, setSymbol] = useState('')
  const [decimals, setDecimals] = useState(2)
  const [sortOrder, setSortOrder] = useState(0)
  const [busy, setBusy] = useState(false)
  const { ref: formRef, error, setError, report, portals } = useFormErrors({ code: 'الكود', name_ar: 'الاسم', symbol: 'الرمز', decimals: 'المنازل العشرية', sort_order: 'الترتيب' })

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post('/settings/currencies', {
        code, name_ar: nameAr, symbol, decimals, sort_order: sortOrder,
      })
      setCode(''); setNameAr(''); setSymbol(''); setDecimals(2); setSortOrder(0)
      onCreated()
    } catch (err) {
      report(err, 'تعذّر إنشاء العملة')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form ref={formRef} onSubmit={submit} className="op-row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 16, alignItems: 'flex-end' }}>
      <div className="field" style={{ maxWidth: 90 }}>
        <label className="field-label" htmlFor="cc-code">الكود</label>
        <input id="cc-code" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} maxLength={8} required />
      </div>
      <div className="field"><label className="field-label" htmlFor="cc-name">الاسم</label><input id="cc-name" value={nameAr} onChange={(e) => setNameAr(e.target.value)} required /></div>
      <div className="field" style={{ maxWidth: 90 }}>
        <label className="field-label" htmlFor="cc-symbol">الرمز</label>
        <input id="cc-symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} required />
      </div>
      <div className="field" style={{ maxWidth: 90 }}>
        <label className="field-label" htmlFor="cc-decimals">المنازل العشرية</label>
        <input id="cc-decimals" type="number" min={0} max={6} value={decimals} onChange={(e) => setDecimals(Number(e.target.value))} />
      </div>
      <div className="field" style={{ maxWidth: 90 }}>
        <label className="field-label" htmlFor="cc-sort">الترتيب</label>
        <input id="cc-sort" type="number" value={sortOrder} onChange={(e) => setSortOrder(Number(e.target.value))} />
      </div>
      <button type="submit" className="btn btn-primary" disabled={busy}>+ عملة جديدة</button>
      {error && <div className="alert alert-critical" style={{ width: '100%' }}>{error}</div>}
      {portals}
    </form>
  )
}

function CurrencyEditRow({ row, onSaved, onCancel }: { row: CurrencyAdminRow; onSaved: () => void; onCancel: () => void }) {
  const [nameAr, setNameAr] = useState(row.name_ar)
  const [symbol, setSymbol] = useState(row.symbol)
  const [decimals, setDecimals] = useState(row.decimals)
  const [sortOrder, setSortOrder] = useState(row.sort_order)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await api.patch(`/settings/currencies/${row.code}`, {
        name_ar: nameAr, symbol, decimals, sort_order: sortOrder,
      })
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
      <td><input value={symbol} onChange={(e) => setSymbol(e.target.value)} style={{ width: 60 }} /></td>
      <td className="num">
        <input
          type="number" min={0} max={6} value={decimals} onChange={(e) => setDecimals(Number(e.target.value))}
          style={{ width: 60 }} title="يُرفَض التعديل إن استُخدمت العملة في قيد حقيقي بالفعل"
        />
      </td>
      <td className="num"><input type="number" value={sortOrder} onChange={(e) => setSortOrder(Number(e.target.value))} style={{ width: 60 }} /></td>
      <td>{row.is_pivot ? <span className="badge badge-usd">محورية</span> : '—'}</td>
      <td><span className={`badge ${row.is_active ? 'badge-status-posted' : 'badge-status-reversed'}`}>{row.is_active ? 'نشطة' : 'معطَّلة'}</span></td>
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

function CurrencyDisplayRow({ row, onEdit, onToggled }: { row: CurrencyAdminRow; onEdit: () => void; onToggled: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function toggle() {
    setBusy(true)
    setError(null)
    try {
      await api.patch(`/settings/currencies/${row.code}`, { is_active: !row.is_active })
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
      <td className="num">{row.symbol}</td>
      <td className="num">{row.decimals}</td>
      <td className="num">{row.sort_order}</td>
      <td>{row.is_pivot ? <span className="badge badge-usd">محورية</span> : '—'}</td>
      <td><span className={`badge ${row.is_active ? 'badge-status-posted' : 'badge-status-reversed'}`}>{row.is_active ? 'نشطة' : 'معطَّلة'}</span></td>
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

export function CurrenciesTab() {
  const [rows, setRows] = useState<CurrencyAdminRow[] | null>(null)
  const [editingCode, setEditingCode] = useState<string | null>(null)

  async function reload() {
    const data = await api.get<CurrencyAdminRow[]>('/settings/currencies')
    setRows(data)
  }

  useEffect(() => { void reload() }, [])

  return (
    <>
      <CreateCurrencyForm onCreated={() => void reload()} />
      {!rows ? <p className="text-muted">...جارٍ التحميل</p> : (
        <table className="data-table">
          <thead><tr>
            <th>الكود</th><th>الاسم</th><th>الرمز</th><th>المنازل العشرية</th><th>الترتيب</th><th>محورية</th><th>الحالة</th><th></th>
          </tr></thead>
          <tbody>
            {rows.map((r) => r.code === editingCode ? (
              <CurrencyEditRow
                key={r.code} row={r}
                onSaved={() => { setEditingCode(null); void reload() }}
                onCancel={() => setEditingCode(null)}
              />
            ) : (
              <CurrencyDisplayRow
                key={r.code} row={r}
                onEdit={() => setEditingCode(r.code)}
                onToggled={() => void reload()}
              />
            ))}
            {rows.length === 0 && <tr><td colSpan={8} className="text-muted">لا عملات مسجَّلة بعد</td></tr>}
          </tbody>
        </table>
      )}
    </>
  )
}
