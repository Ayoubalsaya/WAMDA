import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type {
  AutoMatchResponse, PartnerRow, PartnerStatementDetail, PartnerStatementSummary, StatementLineOut,
} from '../api/types'
import { DecimalError, DecimalInput } from '../components/DecimalInput'
import { decimalInputError } from '../lib/decimalInput'
import './ReconciliationScreen.css'
import { useFormErrors } from '../hooks/useFormErrors'

interface NewLine { value_date: string; description: string; amount: string }

function NewStatementModal({
  partners, onClose, onCreated,
}: { partners: PartnerRow[]; onClose: () => void; onCreated: (s: PartnerStatementDetail) => void }) {
  const [partnerId, setPartnerId] = useState<number | ''>('')
  const [periodFrom, setPeriodFrom] = useState('')
  const [periodTo, setPeriodTo] = useState('')
  const [lines, setLines] = useState<NewLine[]>([{ value_date: '', description: '', amount: '' }])
  const [busy, setBusy] = useState(false)
  const { ref: formRef, error, setError, report, portals } = useFormErrors((key, server) => { const m = key.match(/^lines\.(\d+)\.(\w+)$/); if (m) return `البند ${Number(m[1]) + 1} — ${m[2] === 'amount' ? 'المبلغ' : m[2] === 'value_date' ? 'التاريخ' : 'الوصف'}`; return ({ partner_id: 'الشريك', period_from: 'من تاريخ', period_to: 'إلى تاريخ', lines: 'بنود الكشف' } as Record<string, string>)[key] ?? server ?? 'الحقل' })

  function updateLine(i: number, patch: Partial<NewLine>) {
    setLines((prev) => prev.map((l, idx) => (idx === i ? { ...l, ...patch } : l)))
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    // بند مكتمل جزئياً (مبلغ بلا تاريخ أو العكس) كان يُحذف بصمت من الطلب رغم
    // ظهوره في الشاشة — الآن يُرفض برسالة تسمّي رقم البند.
    const sentLines: NewLine[] = []
    for (const [i, l] of lines.entries()) {
      if (!l.value_date && !l.amount && !l.description) continue
      if (!l.value_date || !l.amount) {
        setError(`البند ${i + 1}: أكمل التاريخ والمبلغ معاً أو احذف البند`)
        return
      }
      const amountError = decimalInputError(l.amount)
      if (amountError) {
        setError(`البند ${i + 1} — «المبلغ»: ${amountError}`)
        return
      }
      sentLines.push(l)
    }
    setBusy(true)
    setError(null)
    try {
      const statement = await api.post<PartnerStatementDetail>('/reconciliation/statements', {
        partner_id: partnerId,
        period_from: periodFrom,
        period_to: periodTo,
        lines: sentLines.map((l) => ({ value_date: l.value_date, description: l.description || undefined, amount: l.amount })),
      })
      onCreated(statement)
    } catch (err) {
      report(err, 'تعذّر إنشاء الكشف')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-veil" role="dialog" aria-modal="true" onClick={onClose}>
      <form ref={formRef} className="card new-op-panel" style={{ width: 520 }} onClick={(e) => e.stopPropagation()} onSubmit={submit}>
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
            <div style={{ flex: 1 }}>
              <DecimalInput placeholder="المبلغ" value={l.amount} onChange={(v) => updateLine(i, { amount: v })} style={{ width: '100%' }} />
              <DecimalError value={l.amount} />
            </div>
          </div>
        ))}
        <button
          type="button" className="btn-text" style={{ marginBottom: 16 }}
          onClick={() => setLines((prev) => [...prev, { value_date: '', description: '', amount: '' }])}
        >
          + بند آخر
        </button>
        {error && <div className="alert alert-critical" style={{ marginBottom: 12 }}>{error}</div>}
        {portals}
        <div className="op-row">
          <button type="button" className="btn btn-secondary" onClick={onClose}>إلغاء</button>
          <button type="submit" className="btn btn-primary" style={{ flex: 1 }} disabled={busy}>حفظ</button>
        </div>
      </form>
    </div>
  )
}

function AdjustModal({
  statementId, line, onClose, onDone,
}: {
  statementId: number
  line: StatementLineOut
  onClose: () => void
  onDone: () => void
}) {
  const [accountCode, setAccountCode] = useState('')
  const [currencyCode, setCurrencyCode] = useState('')
  const [amount, setAmount] = useState(line.amount)
  const [isDebit, setIsDebit] = useState(true)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const { ref: formRef, error, setError, report, portals } = useFormErrors({ account_code: 'حساب المراسل', currency_code: 'العملة', amount: 'المبلغ', is_debit: 'الاتجاه', reason: 'السبب' })

  const reasonOk = reason.trim().length >= 3

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!reasonOk) return // §٥-١٢: لا تسوية بلا سبب
    setBusy(true)
    setError(null)
    try {
      await api.post(`/reconciliation/statements/${statementId}/lines/${line.id}/adjust`, {
        account_code: accountCode, currency_code: currencyCode, amount, is_debit: isDebit, reason: reason.trim(),
      })
      onDone()
    } catch (err) {
      report(err, 'تعذّرت التسوية')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-veil" role="dialog" aria-modal="true" onClick={onClose}>
      <form ref={formRef} className="card new-op-panel" style={{ width: 460 }} onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3 className="card-title" style={{ marginBottom: 4 }}>تسوية الفرق بقيد ADJUSTMENT</h3>
        <div className="text-muted" style={{ fontSize: 'var(--fs-xs)', marginBottom: 14 }}>
          يُرحَّل قيد تسوية ويُربَط بهذا السطر مباشرة. السبب إلزامي (§٥-١٢).
        </div>
        <div className="op-row" style={{ marginBottom: 10 }}>
          <div className="field" style={{ flex: 1.4 }}>
            <label className="field-label" htmlFor="adj-acct">حساب المراسل</label>
            <input id="adj-acct" value={accountCode} onChange={(e) => setAccountCode(e.target.value)} required />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label className="field-label" htmlFor="adj-ccy">العملة</label>
            <input id="adj-ccy" value={currencyCode} onChange={(e) => setCurrencyCode(e.target.value.toUpperCase())} placeholder="USD" required />
          </div>
        </div>
        <div className="op-row" style={{ marginBottom: 10 }}>
          <div className="field" style={{ flex: 1 }}>
            <label className="field-label" htmlFor="adj-amt">المبلغ</label>
            <DecimalInput id="adj-amt" value={amount} onChange={(v) => { setAmount(v); setError(null) }} required />
            <DecimalError value={amount} />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label className="field-label" htmlFor="adj-dir">الاتجاه</label>
            <select id="adj-dir" value={isDebit ? 'debit' : 'credit'} onChange={(e) => setIsDebit(e.target.value === 'debit')}>
              <option value="debit">زيادة رصيد الحساب</option>
              <option value="credit">نقص رصيد الحساب</option>
            </select>
          </div>
        </div>
        <div className="field" style={{ marginBottom: 12 }}>
          <label className="field-label" htmlFor="adj-reason">السبب (إلزامي)</label>
          <textarea
            id="adj-reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} required
            placeholder="مثلاً: فرق مؤكَّد مع الشركة عبر الهاتف — رسوم تحويل لم تُسجَّل"
          />
        </div>
        {error && <div className="alert alert-critical" style={{ marginBottom: 12 }}>{error}</div>}
        {portals}
        <div className="op-row">
          <button type="button" className="btn btn-secondary" onClick={onClose}>إلغاء</button>
          <button type="submit" className="btn btn-primary" style={{ flex: 1 }} disabled={busy || !reasonOk}>
            ترحيل التسوية وربطها
          </button>
        </div>
      </form>
    </div>
  )
}

function TheirLineActions({
  statementId, line, onChanged, onAdjust,
}: { statementId: number; line: StatementLineOut; onChanged: () => void; onAdjust: () => void }) {
  const [entryId, setEntryId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function call(fn: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try { await fn(); onChanged() } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّرت العملية')
    } finally { setBusy(false) }
  }

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginTop: 4 }}>
      <input
        placeholder="رقم القيد" value={entryId} onChange={(e) => setEntryId(e.target.value)}
        style={{ width: 92 }} inputMode="numeric"
      />
      <button type="button" className="btn-text" disabled={busy || !entryId}
        onClick={() => void call(() => api.patch(`/reconciliation/statements/${statementId}/lines/${line.id}/match`, { entry_id: Number(entryId) }))}>
        مطابقة يدوية
      </button>
      <button type="button" className="btn-text" disabled={busy} onClick={onAdjust}>تسوية بقيد ADJUSTMENT</button>
      <button type="button" className="btn-text" disabled={busy}
        onClick={() => void call(() => api.patch(`/reconciliation/statements/${statementId}/lines/${line.id}/resolve`, {}))}>
        تسوية بلا قيد
      </button>
      {error && <span style={{ color: 'var(--red-600, #dc2626)', fontSize: 'var(--fs-xs)' }}>{error}</span>}
    </div>
  )
}

function StatementDetailView({ statementId, onBack }: { statementId: number; onBack: () => void }) {
  const [detail, setDetail] = useState<PartnerStatementDetail | null>(null)
  const [matching, setMatching] = useState(false)
  const [adjustLine, setAdjustLine] = useState<StatementLineOut | null>(null)

  async function reload() {
    setDetail(await api.get<PartnerStatementDetail>(`/reconciliation/statements/${statementId}`))
  }

  useEffect(() => { void reload() }, [statementId])

  async function runAutoMatch() {
    setMatching(true)
    try {
      await api.post<AutoMatchResponse>(`/reconciliation/statements/${statementId}/auto-match`)
      await reload()
    } finally {
      setMatching(false)
    }
  }

  if (!detail) return <p className="text-muted">...جارٍ التحميل</p>

  return (
    <div className="card">
      <div className="op-row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <button type="button" className="btn-text" onClick={onBack}>← رجوع للكشوفات</button>
          <div className="card-title" style={{ marginTop: 8 }}>{detail.partner_name_ar}</div>
          <div className="text-muted" style={{ fontSize: 'var(--fs-xs)' }}>{detail.period_from} → {detail.period_to}</div>
        </div>
        <button type="button" className="btn btn-primary" disabled={matching} onClick={() => void runAutoMatch()}>
          {matching ? '...جارٍ المطابقة' : 'مطابقة تلقائية'}
        </button>
      </div>

      {(detail.unmatched_line_count > 0 || detail.unmatched_entry_count > 0) && (
        <div className="alert alert-warning recon-diff-banner" style={{ marginBottom: 14 }}>
          فروق غير مسوّاة:
          {detail.unmatched_line_count > 0 && <> <b>{detail.unmatched_line_count}</b> في كشفهم بلا قيد عندك ·</>}
          {detail.unmatched_entry_count > 0 && (
            <> <b className="recon-danger">{detail.unmatched_entry_count}</b> قيد عندك بلا سطر في كشفهم
              <span className="text-muted"> (سجّلتها ولم ينفّذوها)</span></>
          )}
        </div>
      )}

      <div className="recon-side-by-side">
        <div className="recon-col">
          <div className="recon-col-head">كشف المراسل ({detail.lines.length})</div>
          <table className="data-table">
            <thead><tr><th>التاريخ</th><th>الوصف</th><th>المبلغ</th><th>الحالة</th></tr></thead>
            <tbody>
              {detail.lines.map((l) => (
                <tr key={l.id} className={l.status === 'OPEN' ? 'recon-open' : ''}>
                  <td className="num">{l.value_date}</td>
                  <td>
                    {l.description ?? '—'}
                    {l.status === 'OPEN' && (
                      <TheirLineActions statementId={statementId} line={l}
                        onChanged={() => void reload()} onAdjust={() => setAdjustLine(l)} />
                    )}
                    {l.matched_entry_no && <div className="text-muted" style={{ fontSize: 'var(--fs-2xs)' }}>↔ {l.matched_entry_no}</div>}
                  </td>
                  <td className="num" style={{ fontWeight: 600 }}>{l.amount}</td>
                  <td><span className={`badge ${l.status === 'RESOLVED' ? 'badge-status-posted' : 'badge-status-reversed'}`}>{l.status === 'RESOLVED' ? 'مُسوَّى' : 'مفتوح'}</span></td>
                </tr>
              ))}
              {detail.lines.length === 0 && <tr><td colSpan={4} className="text-muted">لا بنود</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="recon-col">
          <div className="recon-col-head">دفترك — حركة حساب المراسل ({detail.your_entries.length})</div>
          <table className="data-table">
            <thead><tr><th>التاريخ</th><th>القيد</th><th>النوع</th><th>الأثر</th></tr></thead>
            <tbody>
              {detail.your_entries.map((e) => (
                <tr key={e.entry_id} className={e.matched_line_id === null ? 'recon-danger-row' : ''}>
                  <td className="num">{e.entry_date}</td>
                  <td className="num">{e.entry_no}</td>
                  <td>{e.operation_type}{e.matched_line_id === null && <div className="recon-danger" style={{ fontSize: 'var(--fs-2xs)' }}>لم ينفّذوها بعد</div>}</td>
                  <td className="num" style={{ fontWeight: 600 }}>{e.amount}</td>
                </tr>
              ))}
              {detail.your_entries.length === 0 && <tr><td colSpan={4} className="text-muted">لا حركة في دفترك لهذا المراسل ضمن الفترة</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {adjustLine && (
        <AdjustModal
          statementId={statementId} line={adjustLine}
          onClose={() => setAdjustLine(null)}
          onDone={() => { setAdjustLine(null); void reload() }}
        />
      )}
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
