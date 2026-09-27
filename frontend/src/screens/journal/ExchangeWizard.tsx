import { useMemo, useState } from 'react'
import { X } from 'lucide-react'
import { api, ApiError, newIdempotencyKey } from '../../api/client'
import type { ClientSearchResult, ExchangeChainResponse } from '../../api/types'
import { useReferenceData } from '../../hooks/useReferenceData'
import { PIVOT_CODE, convertPreview, profitOrLossLabel, rateDirectionHint, roundGivenToClient, roundInternal } from '../../lib/fxPreview'
import { AccountPicker, type AccountPickerSpec } from '../../components/AccountPicker'
import { AmountStage, FormGuide, PillTabs } from './journalUi'
import './journal-design.css'

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

  // ٢٠٢٦-٠٩-٢٥: نطاقان (طلب مالك، الفجوة المعلَنة في دفعة الخزينة
  // السابقة) — عميل (الأصل) أو خزينة (بين حسابات شركة، لا عميل إطلاقاً،
  // مثال المالك: دينار عند مكتب ١ ← دولار ← رمبي). نفس منطق OperationForm
  // تماماً — القطبية/الربح معكوسان في نطاق الخزينة، الخادم يحسم ذلك.
  const [scope, setScope] = useState<'CLIENT' | 'TREASURY'>('CLIENT')
  const [step1SourceAccount, setStep1SourceAccount] = useState('')
  const [step1DestAccount, setStep1DestAccount] = useState('')
  const [step2DestAccount, setStep2DestAccount] = useState('')

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

  const step1SourceSpec: AccountPickerSpec | null =
    scope === 'TREASURY' ? { mode: 'operation', operationType: 'EXCHANGE', field: 'source', currencyCode: fromCurrency } : null
  const step1DestSpec: AccountPickerSpec | null =
    scope === 'TREASURY' ? { mode: 'operation', operationType: 'EXCHANGE', field: 'destination', currencyCode: PIVOT_CODE } : null
  const step2DestSpec: AccountPickerSpec | null =
    scope === 'TREASURY' ? { mode: 'operation', operationType: 'EXCHANGE', field: 'destination', currencyCode: toCurrency } : null

  const step1Preview = useMemo(() => {
    const usd = currencies.find((c) => c.code === PIVOT_CODE)
    if (!usd || !amount || !step1Client || !step1Cost) return null
    const clientAmt = roundGivenToClient(convertPreview(amount, step1Client, fromCurrency), usd.decimals)
    const costAmt = roundInternal(convertPreview(amount, step1Cost, fromCurrency), usd.decimals)
    // نطاق الخزينة: الربح = تنفيذ−تكلفة لا تكلفة−عميل (انظر exchange.execute_via_rates)
    const diff = scope === 'TREASURY' ? clientAmt.minus(costAmt) : costAmt.minus(clientAmt)
    return { clientAmt, costAmt, diff }
  }, [amount, step1Client, step1Cost, fromCurrency, currencies, scope])

  const step2Preview = useMemo(() => {
    const to = currencies.find((c) => c.code === toCurrency)
    if (!to || !step1Preview || !step2Client || !step2Cost) return null
    const baseAmount = step1Preview.clientAmt.toString()
    const clientAmt = roundGivenToClient(convertPreview(baseAmount, step2Client, PIVOT_CODE), to.decimals)
    const costAmt = roundInternal(convertPreview(baseAmount, step2Cost, PIVOT_CODE), to.decimals)
    const diff = scope === 'TREASURY' ? clientAmt.minus(costAmt) : costAmt.minus(clientAmt)
    return { clientAmt, costAmt, diff }
  }, [step1Preview, step2Client, step2Cost, toCurrency, currencies, scope])

  const step1Ready = scope === 'TREASURY' ? Boolean(step1SourceAccount && step1DestAccount) : Boolean(fromLocation && step1ToLocation)
  const step2Ready = scope === 'TREASURY' ? Boolean(step2DestAccount) : Boolean(step2ToLocation)

  async function save() {
    if (scope === 'CLIENT' && !client) return
    setBusy(true)
    setError(null)
    try {
      const res = await api.post<ExchangeChainResponse>('/operations/exchange-chain', {
        client_id: scope === 'CLIENT' ? client!.id : undefined,
        step1: {
          from_currency: fromCurrency, to_currency: PIVOT_CODE, amount, cost_rate: step1Cost, client_rate: step1Client,
          negative_margin_reason: step1Reason || undefined,
          ...(scope === 'TREASURY'
            ? { source_account_code: step1SourceAccount, destination_account_code: step1DestAccount }
            : { from_location_code: fromLocation, to_location_code: step1ToLocation }),
        },
        step2: {
          to_currency: toCurrency, cost_rate: step2Cost, client_rate: step2Client,
          negative_margin_reason: step2Reason || undefined,
          ...(scope === 'TREASURY'
            ? { destination_account_code: step2DestAccount }
            : { to_location_code: step2ToLocation }),
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
    <div className="jr-modal-backdrop" role="dialog" aria-modal="true">
      <div className="jr-modal">
        <div className="wizard-progress">
          <div className={`wizard-seg${step >= 1 ? ' is-active' : ''}`} />
          <div className={`wizard-seg${step >= 2 ? ' is-active' : ''}`} />
        </div>
        <button type="button" className="jr-modal-close" aria-label="إغلاق" onClick={onClose}>
          <X size={18} strokeWidth={2} />
        </button>

        <PillTabs
          label="نطاق الصرافة"
          value={scope}
          onChange={setScope}
          options={[{ id: 'CLIENT', label: 'عميل' }, { id: 'TREASURY', label: 'خزينة (بين حسابات شركة)' }]}
        />

        {scope === 'CLIENT' && !client && <FormGuide tone="info">اختر عميلاً من دفتر اليومية أولاً ثم أعد فتح المعالج</FormGuide>}

        {step === 1 && (
          <div>
            <h3 className="card-title">الخطوة ١ — من {currencies.find((c) => c.code === fromCurrency)?.name_ar ?? fromCurrency} إلى الدولار</h3>
            <div className="form-row">
              <div className="field">
                <label className="field-label">من عملة</label>
                <select value={fromCurrency} onChange={(e) => { setFromCurrency(e.target.value); setFromLocation(''); setStep1SourceAccount('') }}>
                  {currencies.filter((c) => c.code !== PIVOT_CODE).map((c) => <option key={c.code} value={c.code}>{c.name_ar}</option>)}
                </select>
              </div>
              {scope === 'CLIENT' && (
                <>
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
                </>
              )}
            </div>
            {scope === 'TREASURY' && (
              <div className="form-row">
                <AccountPicker
                  value={step1SourceAccount} onChange={setStep1SourceAccount} spec={step1SourceSpec} label="الحساب المصدر"
                  emptyMessage={!fromCurrency ? 'اختر العملة أولاً' : 'لا حسابات شركة بهذه العملة'}
                />
                <AccountPicker
                  value={step1DestAccount} onChange={setStep1DestAccount} spec={step1DestSpec} label="الحساب الوجهة (دولار)"
                  emptyMessage="لا حسابات شركة بالدولار"
                />
              </div>
            )}
            <div className="form-row">
              <AmountStage id="wizard-amount" label="المبلغ" value={amount} onChange={setAmount} currencyCode={fromCurrency} />
              <div className="field field-rate">
                <label className="field-label">{scope === 'TREASURY' ? 'سعر التنفيذ' : 'سعر العميل'}</label>
                <input className="num" value={step1Client} onChange={(e) => setStep1Client(e.target.value)} />
              </div>
              <div className="field field-rate">
                <label className="field-label">سعر التكلفة</label>
                <input className="num" value={step1Cost} onChange={(e) => setStep1Cost(e.target.value)} />
              </div>
            </div>
            {step1Preview && (
              <div className={`rate-direction ${step1Preview.diff.gte(0) ? 'money-positive' : 'money-negative'}`}>
                {rateDirectionHint(step1Preview.diff).text}
              </div>
            )}
            {step1Preview && (
              <div className="result-card">
                <div className="result-row"><span>بسعر التنفيذ ← ما أعطيته فعلاً</span><span className="num">{step1Preview.clientAmt.toString()} USD</span></div>
                <div className="result-row result-dashed"><span>بسعر التكلفة ← ما كان يجب أن أحصل عليه</span><span className="num text-muted">{step1Preview.costAmt.toString()} USD</span></div>
                <div className="result-row result-final">
                  <span>{profitOrLossLabel(step1Preview.diff)} الخطوة ١</span>
                  <span className={`num ${step1Preview.diff.gte(0) ? 'money-positive' : 'money-negative'}`}>{step1Preview.diff.toString()} USD</span>
                </div>
              </div>
            )}
            {step1Preview?.diff.lt(0) && (
              <div className="field"><label className="field-label">سبب الهامش السالب</label>
                <input value={step1Reason} onChange={(e) => setStep1Reason(e.target.value)} /></div>
            )}
            <button type="button" className="btn btn-primary btn-lg" style={{ width: '100%' }} onClick={() => setStep(2)} disabled={!step1Preview || !step1Ready}>
              التالي
            </button>
          </div>
        )}

        {step === 2 && (
          <div>
            <h3 className="card-title">الخطوة ٢ — من الدولار إلى {scope === 'TREASURY' ? 'عملة أخرى' : (currencies.find((c) => c.code === toCurrency)?.name_ar ?? toCurrency)}</h3>
            <div className="derived-field">
              المبلغ المُرحَّل من الخطوة ١: <span className="num">{step1Preview?.clientAmt.toString() ?? '—'} USD</span> (مقفل)
            </div>
            <div className="form-row">
              <div className="field">
                <label className="field-label">إلى عملة</label>
                <select value={toCurrency} onChange={(e) => { setToCurrency(e.target.value); setStep2ToLocation(''); setStep2DestAccount('') }}>
                  {currencies.filter((c) => c.code !== PIVOT_CODE).map((c) => <option key={c.code} value={c.code}>{c.name_ar}</option>)}
                </select>
              </div>
              {scope === 'CLIENT' && (
                <div className="field">
                  <label className="field-label">إلى موقع</label>
                  <select value={step2ToLocation} onChange={(e) => setStep2ToLocation(e.target.value)}>
                    <option value="" disabled>اختر</option>
                    {step2ToLocations.map((l) => <option key={l.code} value={l.code}>{l.name_ar}</option>)}
                  </select>
                </div>
              )}
            </div>
            {scope === 'TREASURY' && (
              <AccountPicker
                value={step2DestAccount} onChange={setStep2DestAccount} spec={step2DestSpec} label="الحساب الوجهة"
                emptyMessage={!toCurrency ? 'اختر إلى عملة أولاً' : 'لا حسابات شركة بهذه العملة'}
              />
            )}
            <div className="form-row">
              <div className="field field-rate">
                <label className="field-label">{scope === 'TREASURY' ? 'سعر التنفيذ' : 'سعر العميل'}</label>
                <input className="num" value={step2Client} onChange={(e) => setStep2Client(e.target.value)} />
              </div>
              <div className="field field-rate">
                <label className="field-label">سعر التكلفة</label>
                <input className="num" value={step2Cost} onChange={(e) => setStep2Cost(e.target.value)} />
              </div>
            </div>
            {step2Preview && (
              <div className={`rate-direction ${step2Preview.diff.gte(0) ? 'money-positive' : 'money-negative'}`}>
                {rateDirectionHint(step2Preview.diff).text}
              </div>
            )}
            {step2Preview && (
              <div className="result-card">
                <div className="result-row"><span>بسعر التنفيذ ← ما أعطيته فعلاً</span><span className="num">{step2Preview.clientAmt.toString()} {toCurrency}</span></div>
                <div className="result-row result-dashed"><span>بسعر التكلفة ← ما كان يجب أن أحصل عليه</span><span className="num text-muted">{step2Preview.costAmt.toString()} {toCurrency}</span></div>
                <div className="result-row result-dashed"><span>{profitOrLossLabel(step1Preview!.diff)} الخطوة ١</span><span className="num">{step1Preview!.diff.toString()} USD</span></div>
                <div className="result-row">
                  <span>{profitOrLossLabel(step2Preview.diff)} الخطوة ٢</span>
                  <span className={`num ${step2Preview.diff.gte(0) ? 'money-positive' : 'money-negative'}`}>{step2Preview.diff.toString()} {toCurrency}</span>
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
            {error && <FormGuide tone="critical">{error}</FormGuide>}
            {result ? (
              <>
                <FormGuide tone="success">
                  تم الحفظ — {result.chain_ref} ({result.step1.entry_no} · {result.step2.entry_no})
                </FormGuide>
                <button type="button" className="btn btn-primary btn-lg" style={{ width: '100%' }} onClick={onClose}>
                  إغلاق
                </button>
              </>
            ) : (
              <div className="form-row">
                <button type="button" className="btn btn-secondary" onClick={() => setStep(1)}>السابق</button>
                <button
                  type="button" className="btn btn-primary btn-lg" style={{ flex: 1 }}
                  disabled={busy || !step2Ready || (scope === 'CLIENT' && !client)} onClick={save}
                >
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
