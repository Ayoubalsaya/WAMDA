import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { BeneficiaryFull, Currency } from '../../api/types'
import { CurrencyBadge } from '../../components/CurrencyBadge'

interface BeneficiariesPanelProps {
  clientId: number
  currencies: Currency[]
}

export function BeneficiariesPanel({ clientId, currencies }: BeneficiariesPanelProps) {
  const [list, setList] = useState<BeneficiaryFull[]>([])
  const [loading, setLoading] = useState(true)
  const [formOpen, setFormOpen] = useState(false)
  const [name, setName] = useState('')
  const [accountNumber, setAccountNumber] = useState('')
  const [bankName, setBankName] = useState('')
  const [currencyCode, setCurrencyCode] = useState('')
  const [purpose, setPurpose] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function reload() {
    setLoading(true)
    const rows = await api.get<BeneficiaryFull[]>(`/clients/${clientId}/beneficiaries-full`)
    setList(rows)
    setLoading(false)
  }

  useEffect(() => {
    void reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post(`/clients/${clientId}/beneficiaries`, {
        name, account_number: accountNumber, bank_name: bankName || undefined,
        currency_code: currencyCode, purpose: purpose || undefined,
      })
      setName(''); setAccountNumber(''); setBankName(''); setCurrencyCode(''); setPurpose('')
      setFormOpen(false)
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر إضافة المستفيد')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <div className="clients-header" style={{ marginBottom: 12 }}>
        <div className="card-title">المستفيدون</div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setFormOpen((v) => !v)}>
          {formOpen ? 'إغلاق' : '+ مستفيد جديد'}
        </button>
      </div>

      {formOpen && (
        <form className="op-form-card" style={{ marginBottom: 16 }} onSubmit={submit}>
          <div className="op-row">
            <div className="field">
              <label className="field-label">الاسم</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="field">
              <label className="field-label">العملة</label>
              <select value={currencyCode} onChange={(e) => setCurrencyCode(e.target.value)} required>
                <option value="" disabled>اختر</option>
                {currencies.map((c) => <option key={c.code} value={c.code}>{c.name_ar}</option>)}
              </select>
            </div>
          </div>
          <div className="op-row">
            <div className="field">
              <label className="field-label">رقم الحساب (إلزامي)</label>
              <input value={accountNumber} onChange={(e) => setAccountNumber(e.target.value)} required />
            </div>
            <div className="field">
              <label className="field-label">اسم البنك (اختياري)</label>
              <input value={bankName} onChange={(e) => setBankName(e.target.value)} />
            </div>
          </div>
          <div className="field">
            <label className="field-label">الغرض (اختياري)</label>
            <input value={purpose} onChange={(e) => setPurpose(e.target.value)} />
          </div>
          {error && <div className="alert alert-critical">{error}</div>}
          <button type="submit" className="btn btn-primary" disabled={busy}>حفظ المستفيد</button>
        </form>
      )}

      {loading && <p className="text-muted">...جارٍ التحميل</p>}
      {!loading && list.length === 0 && <p className="text-muted" style={{ fontSize: 13 }}>لا مستفيدون بعد</p>}
      <div className="beneficiaries-list">
        {list.map((b) => (
          <div key={b.id} className={`beneficiary-row${b.is_active ? '' : ' is-disabled'}`}>
            <div>
              <div style={{ fontWeight: 600 }}>{b.name} <CurrencyBadge code={b.currency_code} /></div>
              <div className="num text-muted" style={{ fontSize: 12 }}>
                {b.account_number}{b.bank_name ? ` · ${b.bank_name}` : ''}
              </div>
            </div>
            <BeneficiaryToggle beneficiary={b} onChanged={reload} />
          </div>
        ))}
      </div>
    </div>
  )
}

function BeneficiaryToggle({ beneficiary, onChanged }: { beneficiary: BeneficiaryFull; onChanged: () => Promise<void> }) {
  const [busy, setBusy] = useState(false)
  async function toggle() {
    setBusy(true)
    try {
      await api.patch(`/beneficiaries/${beneficiary.id}`, { is_active: !beneficiary.is_active })
      await onChanged()
    } finally {
      setBusy(false)
    }
  }
  return (
    <button
      type="button" className={`btn btn-sm ${beneficiary.is_active ? 'btn-danger' : 'btn-secondary'}`}
      disabled={busy} onClick={() => void toggle()}
    >
      {beneficiary.is_active ? 'تعطيل' : 'تفعيل'}
    </button>
  )
}
