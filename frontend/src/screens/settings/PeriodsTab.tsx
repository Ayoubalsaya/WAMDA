import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { FoundingPeriodStatus, PeriodRow } from '../../api/types'
import { useFormErrors } from '../../hooks/useFormErrors'

const MONTH_NAMES = [
  'يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو',
  'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر',
]

function CloseOrReopenForm({ onDone }: { onDone: () => void }) {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [busy, setBusy] = useState(false)
  const { ref: formRef, error, setError, report, portals } = useFormErrors({ year: 'السنة', month: 'الشهر' })

  async function submit(action: 'close' | 'reopen') {
    setBusy(true)
    setError(null)
    try {
      await api.post(`/periods/${action}`, { year, month })
      onDone()
    } catch (err) {
      report(err, 'تعذّرت العملية')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div ref={formRef} className="op-row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 16, alignItems: 'flex-end' }}>
      <div className="field">
        <label className="field-label" htmlFor="period-year">السنة</label>
        <input id="period-year" type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} style={{ width: 100 }} />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="period-month">الشهر</label>
        <select id="period-month" value={month} onChange={(e) => setMonth(Number(e.target.value))}>
          {MONTH_NAMES.map((name, i) => <option key={i} value={i + 1}>{name}</option>)}
        </select>
      </div>
      <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void submit('close')}>إقفال الفترة</button>
      <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void submit('reopen')}>فتح فترة مقفلة</button>
      {error && <div className="alert alert-critical" style={{ width: '100%' }}>{error}</div>}
      {portals}
    </div>
  )
}

function MonthlyPeriodsSection() {
  const [rows, setRows] = useState<PeriodRow[] | null>(null)

  async function reload() {
    const data = await api.get<PeriodRow[]>('/periods')
    setRows(data)
  }

  useEffect(() => { void reload() }, [])

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-title" style={{ marginBottom: 12 }}>الإقفال الشهري</div>
      <CloseOrReopenForm onDone={() => void reload()} />
      {!rows ? <p className="text-muted">...جارٍ التحميل</p> : (
        <table className="data-table">
          <thead><tr><th>السنة</th><th>الشهر</th><th>الحالة</th><th>آخر إقفال بواسطة</th><th>التاريخ</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.year}-${r.month}`}>
                <td className="num">{r.year}</td>
                <td>{MONTH_NAMES[r.month - 1]}</td>
                <td><span className={`badge ${r.is_closed ? 'badge-status-reversed' : 'badge-status-posted'}`}>{r.is_closed ? 'مُقفلة' : 'مفتوحة'}</span></td>
                <td className="text-muted">{r.closed_by_username ?? '—'}</td>
                <td className="num text-muted">{r.closed_at ? new Date(r.closed_at).toLocaleString('ar-LY') : '—'}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="text-muted">لا فترات مُسجَّلة بعد</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  )
}

function FoundingPeriodSection() {
  const [status, setStatus] = useState<FoundingPeriodStatus | null>(null)
  const [acknowledge, setAcknowledge] = useState(false)
  const [busy, setBusy] = useState(false)
  const { ref: formRef, error, setError, report, portals } = useFormErrors({  })

  async function reload() {
    const data = await api.get<FoundingPeriodStatus>('/periods/founding')
    setStatus(data)
  }

  useEffect(() => { void reload() }, [])

  async function close() {
    setBusy(true)
    setError(null)
    try {
      const updated = await api.post<FoundingPeriodStatus>('/periods/founding/close', {
        acknowledged_remaining_suspense: acknowledge,
      })
      setStatus(updated)
    } catch (err) {
      report(err, 'تعذّر إقفال الفترة التأسيسية')
    } finally {
      setBusy(false)
    }
  }

  if (!status) return <p className="text-muted">...جارٍ التحميل</p>
  const suspenseEntries = Object.entries(status.suspense_balance_by_currency)

  return (
    <div ref={formRef} className="card">
      <div className="card-title" style={{ marginBottom: 12 }}>الفترة التأسيسية</div>
      <div style={{ marginBottom: 12 }}>
        الحالة: <span className={`badge ${status.is_open ? 'badge-status-posted' : 'badge-status-reversed'}`}>{status.is_open ? 'مفتوحة' : 'مُقفلة'}</span>
        {!status.is_open && status.closed_by_username && (
          <span className="text-muted" style={{ marginRight: 8 }}>أُقفلت بواسطة {status.closed_by_username}</span>
        )}
      </div>
      {suspenseEntries.length > 0 ? (
        <div className="balances-box" style={{ marginBottom: 12, maxWidth: 320 }}>
          <div className="lbl" style={{ marginBottom: 6 }}>رصيد فروق التأسيس (٣٩٠٠) غير صفري</div>
          {suspenseEntries.map(([ccy, amount]) => (
            <div key={ccy} className="row" style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>{ccy}</span><span className="num">{amount}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-muted" style={{ fontSize: 13 }}>رصيد فروق التأسيس صفري في كل العملات</p>
      )}
      {status.is_open && (
        <>
          {suspenseEntries.length > 0 && (
            <label className="field-label" style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
              <input type="checkbox" checked={acknowledge} onChange={(e) => setAcknowledge(e.target.checked)} />
              أقرّ بأن رصيد فروق التأسيس أعلاه سيبقى غير مُسوَّى بعد الإقفال
            </label>
          )}
          <button
            type="button" className="btn btn-primary" disabled={busy || (suspenseEntries.length > 0 && !acknowledge)}
            onClick={() => void close()}
          >
            إقفال الفترة التأسيسية
          </button>
        </>
      )}
      {error && <div className="alert alert-critical" style={{ marginTop: 12 }}>{error}</div>}
      {portals}
    </div>
  )
}

export function PeriodsTab() {
  return (
    <>
      <MonthlyPeriodsSection />
      <FoundingPeriodSection />
    </>
  )
}
