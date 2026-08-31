import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { AutoMatchResponse, PartnerRow, PartnerStatementDetail, PartnerStatementSummary } from '../api/types'
import './ReconciliationScreen.css'

interface NewLine { value_date: string; description: string; amount: string }

function NewStatementModal({
  partners, onClose, onCreated,
}: { partners: PartnerRow[]; onClose: () => void; onCreated: (s: PartnerStatementDetail) => void }) {
  const [partnerId, setPartnerId] = useState<number | ''>('')
  const [periodFrom, setPeriodFrom] = useState('')
  const [periodTo, setPeriodTo] = useState('')
  const [lines, setLines] = useState<NewLine[]>([{ value_date: '', description: '', amount: '' }])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function updateLine(i: number, patch: Partial<NewLine>) {
    setLines((prev) => prev.map((l, idx) => (idx === i ? { ...l, ...patch } : l)))
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const statement = await api.post<PartnerStatementDetail>('/reconciliation/statements', {
        partner_id: partnerId,
        period_from: periodFrom,
        period_to: periodTo,
        lines: lines
          .filter((l) => l.value_date && l.amount)
          .map((l) => ({ value_date: l.value_date, description: l.description || undefined, amount: l.amount })),
      })
      onCreated(statement)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر إنشاء الكشف')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-veil" role="dialog" aria-modal="true" onClick={onClose}>
      <form className="card new-op-panel" style={{ width: 520 }} onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3 className="card-title" style={{ marginBottom: 16 }}>كشف مراسل جديد</h3>
        <div className="field" style={{ marginBottom: 12 }}>
          <label className="field-label" htmlFor="recon-partner">الشريك</label>
          <select id="recon-partner" value={partnerId} onChange={(e) => setPartnerId(Number(e.target.value))} required>
            <option value="">اختر شريكاً...</option>
            {partners.map((p) => <option key={p.id} value={p.id}>{p.name_ar}</option>)}
          </select>
        </div>
        <div className="op-row" style={{ marginBottom: 12 }}>
          <div className="field" style={{ flex: 1 }}>
            <label className="field-label" htmlFor="recon-from">من تاريخ</label>
            <input id="recon-from" type="date" value={periodFrom} onChange={(e) => setPeriodFrom(e.target.value)} required />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label className="field-label" htmlFor="recon-to">إلى تاريخ</label>
            <input id="recon-to" type="date" value={periodTo} onChange={(e) => setPeriodTo(e.target.value)} required />
          </div>
        </div>
        <div className="field-label" style={{ marginBottom: 6 }}>بنود الكشف</div>
        {lines.map((l, i) => (
          <div className="op-row" key={i} style={{ marginBottom: 8 }}>
            <input type="date" value={l.value_date} onChange={(e) => updateLine(i, { value_date: e.target.value })} style={{ flex: 1 }} />
            <input placeholder="الوصف" value={l.description} onChange={(e) => updateLine(i, { description: e.target.value })} style={{ flex: 1.4 }} />
            <input placeholder="المبلغ" inputMode="decimal" value={l.amount} onChange={(e) => updateLine(i, { amount: e.target.value })} style={{ flex: 1 }} />
          </div>
        ))}
        <button
          type="button" className="btn-text" style={{ marginBottom: 16 }}
          onClick={() => setLines((prev) => [...prev, { value_date: '', description: '', amount: '' }])}
        >
          + بند آخر
        </button>
        {error && <div className="alert alert-critical" style={{ marginBottom: 12 }}>{error}</div>}
        <div className="op-row">
          <button type="button" className="btn btn-secondary" onClick={onClose}>إلغاء</button>
          <button type="submit" className="btn btn-primary" style={{ flex: 1 }} disabled={busy}>حفظ</button>
        </div>
      </form>
    </div>
  )
}

function ManualMatchRow({
  statementId, line, onChanged,
}: { statementId: number; line: PartnerStatementDetail['lines'][number]; onChanged: () => void }) {
  const [entryId, setEntryId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function match() {
    if (!entryId) return
    setBusy(true)
    setError(null)
    try {
      await api.patch(`/reconciliation/statements/${statementId}/lines/${line.id}/match`, { entry_id: Number(entryId) })
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّرت المطابقة')
    } finally {
      setBusy(false)
    }
  }

  async function resolveWithoutEntry() {
    setBusy(true)
    setError(null)
    try {
      await api.patch(`/reconciliation/statements/${statementId}/lines/${line.id}/resolve`, {})
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّرت التسوية')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="op-row" style={{ gap: 6, alignItems: 'center' }}>
      <input
        placeholder="رقم القيد" value={entryId} onChange={(e) => setEntryId(e.target.value)}
        style={{ width: 100 }} inputMode="numeric"
      />
      <button type="button" className="btn-text" disabled={busy || !entryId} onClick={() => void match()}>مطابقة يدوية</button>
      <button type="button" className="btn-text" disabled={busy} onClick={() => void resolveWithoutEntry()}>تسوية بلا قيد</button>
      {error && <span style={{ color: 'var(--red-600, #dc2626)', fontSize: 12 }}>{error}</span>}
    </div>
  )
}

function StatementDetailView({ statementId, onBack }: { statementId: number; onBack: () => void }) {
  const [detail, setDetail] = useState<PartnerStatementDetail | null>(null)
  const [matching, setMatching] = useState(false)

  async function reload() {
    const d = await api.get<PartnerStatementDetail>(`/reconciliation/statements/${statementId}`)
    setDetail(d)
  }

  useEffect(() => { void reload() }, [statementId])

  async function runAutoMatch() {
    setMatching(true)
    try {
      const result = await api.post<AutoMatchResponse>(`/reconciliation/statements/${statementId}/auto-match`)
      setDetail(result.statement)
    } finally {
      setMatching(false)
    }
  }

  if (!detail) return <p className="text-muted">...جارٍ التحميل</p>

  return (
    <div className="card">
      <div className="op-row" style={{ justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <button type="button" className="btn-text" onClick={onBack}>← رجوع للكشوفات</button>
          <div className="card-title" style={{ marginTop: 8 }}>{detail.partner_name_ar}</div>
          <div className="text-muted" style={{ fontSize: 12.5 }}>{detail.period_from} → {detail.period_to}</div>
        </div>
        <button type="button" className="btn btn-primary" disabled={matching} onClick={() => void runAutoMatch()}>
          {matching ? '...جارٍ المطابقة' : 'مطابقة تلقائية'}
        </button>
      </div>
      <table className="data-table">
        <thead><tr><th>التاريخ</th><th>الوصف</th><th>المبلغ</th><th>الحالة</th><th>القيد المطابق</th><th></th></tr></thead>
        <tbody>
          {detail.lines.map((l) => (
            <tr key={l.id}>
              <td className="num">{l.value_date}</td>
              <td>{l.description ?? '—'}</td>
              <td className="num" style={{ fontWeight: 600 }}>{l.amount}</td>
              <td><span className={`badge ${l.status === 'RESOLVED' ? 'badge-status-posted' : 'badge-status-reversed'}`}>{l.status === 'RESOLVED' ? 'مُسوَّى' : 'مفتوح'}</span></td>
              <td className="num text-muted">{l.matched_entry_no ?? '—'}</td>
              <td>{l.status === 'OPEN' && <ManualMatchRow statementId={statementId} line={l} onChanged={() => void reload()} />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StatementsListView({ onSelect, onCreate }: { onSelect: (id: number) => void; onCreate: () => void }) {
  const [rows, setRows] = useState<PartnerStatementSummary[] | null>(null)
  useEffect(() => { void api.get<PartnerStatementSummary[]>('/reconciliation/statements').then(setRows) }, [])

  return (
    <div className="card">
      <div className="op-row" style={{ justifyContent: 'space-between', marginBottom: 16 }}>
        <div className="card-title">كشوفات المراسلين</div>
        <button type="button" className="btn btn-primary" onClick={onCreate}>+ كشف جديد</button>
      </div>
      {!rows ? <p className="text-muted">...جارٍ التحميل</p> : (
        <table className="data-table">
          <thead><tr><th>الشريك</th><th>الفترة</th><th>عدد البنود</th><th>مفتوحة</th></tr></thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} className="acc-lot-row" onClick={() => onSelect(s.id)}>
                <td>{s.partner_name_ar}</td>
                <td className="num">{s.period_from} → {s.period_to}</td>
                <td className="num">{s.total_lines}</td>
                <td className={`num ${s.open_lines > 0 ? 'money-negative' : 'money-positive'}`} style={{ fontWeight: 700 }}>{s.open_lines}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={4} className="text-muted">لا كشوفات مطابقة بعد</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  )
}

export function ReconciliationScreen() {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [partners, setPartners] = useState<PartnerRow[]>([])
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => { void api.get<PartnerRow[]>('/partners').then(setPartners) }, [])

  return (
    <div className="journal-screen reconciliation-screen">
      <h2 className="screen-title" style={{ marginBottom: 16 }}>المطابقة</h2>
      {selectedId ? (
        <StatementDetailView statementId={selectedId} onBack={() => { setSelectedId(null); setRefreshToken((v) => v + 1) }} />
      ) : (
        <StatementsListView key={refreshToken} onSelect={setSelectedId} onCreate={() => setCreateOpen(true)} />
      )}
      {createOpen && (
        <NewStatementModal
          partners={partners}
          onClose={() => setCreateOpen(false)}
          onCreated={(s) => { setCreateOpen(false); setSelectedId(s.id) }}
        />
      )}
    </div>
  )
}
