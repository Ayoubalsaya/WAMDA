import { useMemo, useState } from 'react'
import { api, ApiError, newIdempotencyKey } from '../../api/client'
import type { ClientSearchResult, ExchangeChainResponse } from '../../api/types'
import { useReferenceData } from '../../hooks/useReferenceData'
import { PIVOT_CODE, convertPreview, roundGivenToClient, roundInternal } from '../../lib/fxPreview'

interface ExchangeWizardProps {
  client: ClientSearchResult | null
  onClose: () => void
  onPosted: (res: ExchangeChainResponse) => void
}

export function ExchangeWizard({ client, onClose, onPosted }: ExchangeWizardProps) {
  const { currencies, locationsForCurrency } = useReferenceData()
  const [step, setStep] = useState<1 | 2>(1)
  const [idemKey] = useState(newIdempotencyKey())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ExchangeChainResponse | null>(null)

  const [fromCurrency, setFromCurrency] = useState('LYD')
  const [fromLocation, setFromLocation] = useState('')
  const [step1ToLocation, setStep1ToLocation] = useState('')
  const [amount, setAmount] = useState('')
  const [step1Cost, setStep1Cost] = useState('')
  const [step1Client, setStep1Client] = useState('')
  const [step1Reason, setStep1Reason] = useState('')

  const [toCurrency, setToCurrency] = useState('CNY')
  const [step2ToLocation, setStep2ToLocation] = useState('')
  const [step2Cost, setStep2Cost] = useState('')
  const [step2Client, setStep2Client] = useState('')
  const [step2Reason, setStep2Reason] = useState('')
  const [note, setNote] = useState('')

  const step1FromLocations = useMemo(() => locationsForCurrency(fromCurrency), [fromCurrency, locationsForCurrency])
  const step1ToLocations = useMemo(() => locationsForCurrency(PIVOT_CODE), [locationsForCurrency])
  const step2ToLocations = useMemo(() => locationsForCurrency(toCurrency), [toCurrency, locationsForCurrency])

  const step1Preview = useMemo(() => {
    const usd = currencies.find((c) => c.code === PIVOT_CODE)
    if (!usd || !amount || !step1Client || !step1Cost) return null
    const clientAmt = roundGivenToClient(convertPreview(amount, step1Client, fromCurrency), usd.decimals)
    const costAmt = roundInternal(convertPreview(amount, step1Cost, fromCurrency), usd.decimals)
    return { clientAmt, costAmt, diff: costAmt.minus(clientAmt) }
  }, [amount, step1Client, step1Cost, fromCurrency, currencies])

  const step2Preview = useMemo(() => {
    const to = currencies.find((c) => c.code === toCurrency)
    if (!to || !step1Preview || !step2Client || !step2Cost) return null
    const baseAmount = step1Preview.clientAmt.toString()
    const clientAmt = roundGivenToClient(convertPreview(baseAmount, step2Client, PIVOT_CODE), to.decimals)
    const costAmt = roundInternal(convertPreview(baseAmount, step2Cost, PIVOT_CODE), to.decimals)
    return { clientAmt, costAmt, diff: costAmt.minus(clientAmt) }
  }, [step1Preview, step2Client, step2Cost, toCurrency, currencies])

  async function save() {
    if (!client) return
    setBusy(true)
    setError(null)
    try {
      const res = await api.post<ExchangeChainResponse>('/operations/exchange-chain', {
        client_id: client.id,
        step1: {
          from_currency: fromCurrency, from_location_code: fromLocation, to_currency: PIVOT_CODE,
          to_location_code: step1ToLocation, amount, cost_rate: step1Cost, client_rate: step1Client,
          negative_margin_reason: step1Reason || undefined,
        },
        step2: {
          to_currency: toCurrency, to_location_code: step2ToLocation, cost_rate: step2Cost,
          client_rate: step2Client, negative_margin_reason: step2Reason || undefined,
        },
        note: note || undefined,
      }, idemKey)
      setResult(res)
      onPosted(res)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر حفظ السلسلة')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-veil" role="dialog" aria-modal="true">
      <div className="wizard-panel card">
        <div className="wizard-progress">
          <div className={`wizard-seg${step >= 1 ? ' is-active' : ''}`} />
          <div className={`wizard-seg${step >= 2 ? ' is-active' : ''}`} />
        </div>
        <button type="button" className="btn-text wizard-close" onClick={onClose}>إغلاق ×</button>

        {!client && <div className="alert alert-info">اختر عميلاً من دفتر اليومية أولاً ثم أعد فتح المعالج</div>}

        {step === 1 && (
          <div>
            <h3 className="card-title">الخطوة ١ — من الدينار إلى الدولار</h3>
            <div className="op-row">
              <div className="field">
                <label className="field-label">من عملة</label>
                <select value={fromCurrency} onChange={(e) => { setFromCurrency(e.target.value); setFromLocation('') }}>
                  {currencies.filter((c) => c.code !== PIVOT_CODE).map((c) => <option key={c.code} value={c.code}>{c.name_ar}</option>)}
                </select>
              </div>
              <div className="field">
                <label className="field-label">من موقع</label>
                <select value={fromLocation} onChange={(e) => setFromLocation(e.target.value)}>
                  <option value="" disabled>اختر</option>
                  {step1FromLocations.map((l) => <option key={l.code} value={l.code}>{l.name_ar}</option>)}
                </select>
              </div>
              <div className="field">
                <label className="field-label">موقع الدولار</label>
                <select value={step1ToLocation} onChange={(e) => setStep1ToLocation(e.target.value)}>
                  <option value="" disabled>اختر</option>
                  {step1ToLocations.map((l) => <option key={l.code} value={l.code}>{l.name_ar}</option>)}
                </select>
              </div>
            </div>
            <div className="op-row">
              <div className="field field-amount">
                <label className="field-label">المبلغ</label>
                <input className="num" value={amount} onChange={(e) => setAmount(e.target.value)} />
              </div>
              <div className="field field-rate">
                <label className="field-label">سعر العميل</label>
                <input className="num" value={step1Client} onChange={(e) => setStep1Client(e.target.value)} />
              </div>
              <div className="field field-rate">
                <label className="field-label">سعر التكلفة</label>
                <input className="num" value={step1Cost} onChange={(e) => setStep1Cost(e.target.value)} />
              </div>
            </div>
            {step1Preview && (
              <div className="result-card">
                <div className="result-row"><span>الدولار الناتج</span><span className="num">{step1Preview.clientAmt.toString()} USD</span></div>
                <div className="result-row result-final">
                  <span>ربح الخطوة ١</span>
                  <span className={`num ${step1Preview.diff.gte(0) ? 'money-positive' : 'money-negative'}`}>{step1Preview.diff.toString()} USD</span>
                </div>
              </div>
            )}
            {step1Preview?.diff.lt(0) && (
              <div className="field"><label className="field-label">سبب الهامش السالب</label>
                <input value={step1Reason} onChange={(e) => setStep1Reason(e.target.value)} /></div>
            )}
            <button type="button" className="btn btn-primary btn-lg" style={{ width: '100%' }} onClick={() => setStep(2)} disabled={!step1Preview}>
              التالي
            </button>
          </div>
        )}

        {step === 2 && (
          <div>
            <h3 className="card-title">الخطوة ٢ — من الدولار إلى الرمبي</h3>
            <div className="derived-field">
              المبلغ المُرحَّل من الخطوة ١: <span className="num">{step1Preview?.clientAmt.toString() ?? '—'} USD</span> (مقفل)
            </div>
            <div className="op-row">
              <div className="field">
                <label className="field-label">إلى عملة</label>
                <select value={toCurrency} onChange={(e) => { setToCurrency(e.target.value); setStep2ToLocation('') }}>
                  {currencies.filter((c) => c.code !== PIVOT_CODE).map((c) => <option key={c.code} value={c.code}>{c.name_ar}</option>)}
                </select>
              </div>
              <div className="field">
                <label className="field-label">إلى موقع</label>
                <select value={step2ToLocation} onChange={(e) => setStep2ToLocation(e.target.value)}>
                  <option value="" disabled>اختر</option>
                  {step2ToLocations.map((l) => <option key={l.code} value={l.code}>{l.name_ar}</option>)}
                </select>
              </div>
            </div>
            <div className="op-row">
              <div className="field field-rate">
                <label className="field-label">سعر العميل</label>
                <input className="num" value={step2Client} onChange={(e) => setStep2Client(e.target.value)} />
              </div>
              <div className="field field-rate">
                <label className="field-label">سعر التكلفة</label>
                <input className="num" value={step2Cost} onChange={(e) => setStep2Cost(e.target.value)} />
              </div>
            </div>
            {step2Preview && (
              <div className="result-card">
                <div className="result-row"><span>الرمبي الناتج</span><span className="num">{step2Preview.clientAmt.toString()} CNY</span></div>
                <div className="result-row result-dashed"><span>ربح الخطوة ١</span><span className="num">{step1Preview?.diff.toString()} USD</span></div>
                <div className="result-row">
                  <span>ربح الخطوة ٢</span>
                  <span className={`num ${step2Preview.diff.gte(0) ? 'money-positive' : 'money-negative'}`}>{step2Preview.diff.toString()} CNY</span>
                </div>
                <div className="result-row result-final"><span>الإجمالي (لأغراض العرض فقط — ربحان منفصلان دائماً في السجلات)</span></div>
              </div>
            )}
            {step2Preview?.diff.lt(0) && (
              <div className="field"><label className="field-label">سبب الهامش السالب</label>
                <input value={step2Reason} onChange={(e) => setStep2Reason(e.target.value)} /></div>
            )}
            <div className="field">
              <label className="field-label" htmlFor="chain-note">ملاحظة (اختياري)</label>
              <textarea id="chain-note" value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
            </div>
            {error && <div className="alert alert-critical">{error}</div>}
            {result ? (
              <>
                <div className="alert alert-info">
                  تم الحفظ — {result.chain_ref} ({result.step1.entry_no} · {result.step2.entry_no})
                </div>
                <button type="button" className="btn btn-primary btn-lg" style={{ width: '100%' }} onClick={onClose}>
                  إغلاق
                </button>
              </>
            ) : (
              <div className="op-row">
                <button type="button" className="btn btn-secondary" onClick={() => setStep(1)}>السابق</button>
                <button type="button" className="btn btn-primary btn-lg" style={{ flex: 1 }} disabled={busy || !client} onClick={save}>
                  حفظ السلسلة
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
