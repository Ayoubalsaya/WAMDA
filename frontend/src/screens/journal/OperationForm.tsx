import { useEffect, useMemo, useState } from 'react'
import { api, ApiError, newIdempotencyKey } from '../../api/client'
import type { AccountRef, ClientSearchResult, Currency, EntryResponse, Location } from '../../api/types'
import { PIVOT_CODE, convertPreview, roundGivenToClient, roundInternal } from '../../lib/fxPreview'
import { useReferenceData } from '../../hooks/useReferenceData'

type OpTab = 'RECEIPT' | 'PAYMENT' | 'EXCHANGE' | 'CASH_TRANSFER'

const TABS: { id: OpTab; label: string }[] = [
  { id: 'RECEIPT', label: 'قبض' },
  { id: 'PAYMENT', label: 'صرف' },
  { id: 'EXCHANGE', label: 'صرافة' },
  { id: 'CASH_TRANSFER', label: 'تحويل بعمولة' },
]

function CurrencySelect({ value, onChange, currencies }: { value: string; onChange: (v: string) => void; currencies: Currency[] }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="" disabled>العملة</option>
      {currencies.map((c) => <option key={c.code} value={c.code}>{c.name_ar}</option>)}
    </select>
  )
}

function LocationSelect({ value, onChange, locations, disabled }: { value: string; onChange: (v: string) => void; locations: Location[]; disabled?: boolean }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
      <option value="" disabled>الموقع</option>
      {locations.map((l) => <option key={l.code} value={l.code}>{l.name_ar}</option>)}
    </select>
  )
}

function AccountSelect({ value, onChange, accounts, label }: { value: string; onChange: (v: string) => void; accounts: AccountRef[]; label: string }) {
  return (
    <div className="field">
      <label className="field-label">{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="" disabled>اختر حساباً</option>
        {accounts.map((a) => <option key={a.code} value={a.code}>{a.code} — {a.name_ar}</option>)}
      </select>
    </div>
  )
}

interface OperationFormProps {
  client: ClientSearchResult | null
  onPosted: (entry: EntryResponse) => void
  onOpenWizard: () => void
  requestedTab?: string | null
}

export function OperationForm({ client, onPosted, onOpenWizard, requestedTab }: OperationFormProps) {
  const { currencies, accounts, locationsForCurrency } = useReferenceData()
  const [tab, setTab] = useState<OpTab>('RECEIPT')
  const [idemKey, setIdemKey] = useState(newIdempotencyKey())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<EntryResponse | null>(null)

  // حقول مشتركة/خاصة — كائن مسطّح واحد، الحقول غير المستخدمة للنوع الحالي تُتجاهل
  const [currencyCode, setCurrencyCode] = useState('')
  const [locationCode, setLocationCode] = useState('')
  const [amount, setAmount] = useState('')
  const [accountCode, setAccountCode] = useState('')

  const [toCurrency, setToCurrency] = useState('')
  const [toLocation, setToLocation] = useState('')
  const [costRate, setCostRate] = useState('')
  const [clientRate, setClientRate] = useState('')
  const [negativeMarginReason, setNegativeMarginReason] = useState('')

  const [fromLocation, setFromLocation] = useState('')
  const [toLocationCt, setToLocationCt] = useState('')
  const [sourceAccount, setSourceAccount] = useState('')
  const [executionAccount, setExecutionAccount] = useState('')
  const [collectionAccount, setCollectionAccount] = useState('')
  const [commissionCurrency, setCommissionCurrency] = useState('')
  const [clientCommission, setClientCommission] = useState('')
  const [costCommission, setCostCommission] = useState('')
  const [costCorrespondentAccount, setCostCorrespondentAccount] = useState('')

  function resetForm() {
    setCurrencyCode(''); setLocationCode(''); setAmount(''); setAccountCode('')
    setToCurrency(''); setToLocation(''); setCostRate(''); setClientRate(''); setNegativeMarginReason('')
    setFromLocation(''); setToLocationCt(''); setCommissionCurrency('')
    setClientCommission(''); setCostCommission(''); setSourceAccount(''); setExecutionAccount('')
    setCollectionAccount(''); setCostCorrespondentAccount('')
    setIdemKey(newIdempotencyKey())
    setSuccess(null)
  }

  useEffect(() => { resetForm() }, [tab])

  useEffect(() => {
    if (requestedTab && TABS.some((t) => t.id === requestedTab)) setTab(requestedTab as OpTab)
  }, [requestedTab])

  const fromLocations = useMemo(() => locationsForCurrency(currencyCode), [currencyCode, locationsForCurrency])
  const toLocations = useMemo(() => locationsForCurrency(toCurrency), [toCurrency, locationsForCurrency])
  const ctFromLocations = useMemo(() => locationsForCurrency(currencyCode), [currencyCode, locationsForCurrency])
  const ctToLocations = useMemo(() => locationsForCurrency(currencyCode), [currencyCode, locationsForCurrency])

  // معاينة فورية في المتصفح — decimal.js فقط، السيرفر يعيد الحساب ويحسم
  const exchangePreview = useMemo(() => {
    if (tab !== 'EXCHANGE' || !currencyCode || !toCurrency || !amount) return null
    const toCcy = currencies.find((c) => c.code === toCurrency)
    if (!toCcy) return null
    const clientRaw = convertPreview(amount, clientRate, currencyCode)
    const costRaw = convertPreview(amount, costRate, currencyCode)
    const clientAmt = roundGivenToClient(clientRaw, toCcy.decimals)
    const costAmt = roundInternal(costRaw, toCcy.decimals)
    const diff = costAmt.minus(clientAmt)
    return { clientAmt, costAmt, diff }
  }, [tab, currencyCode, toCurrency, amount, clientRate, costRate, currencies])

  async function submit() {
    if (!client) {
      setError('اختر عميلاً أولاً')
      return
    }
    setBusy(true)
    setError(null)
    try {
      let entry: EntryResponse
      if (tab === 'RECEIPT') {
        entry = await api.post<EntryResponse>('/operations/receipt', {
          client_id: client.id, currency_code: currencyCode, location_code: locationCode,
          amount, receiving_account_code: accountCode,
        }, idemKey)
      } else if (tab === 'PAYMENT') {
        entry = await api.post<EntryResponse>('/operations/payment', {
          client_id: client.id, currency_code: currencyCode, location_code: locationCode,
          amount, paying_account_code: accountCode,
        }, idemKey)
      } else if (tab === 'EXCHANGE') {
        entry = await api.post<EntryResponse>('/operations/exchange', {
          client_id: client.id, from_currency: currencyCode, from_location_code: locationCode,
          to_currency: toCurrency, to_location_code: toLocation, amount, cost_rate: costRate,
          client_rate: clientRate, negative_margin_reason: negativeMarginReason || undefined,
        }, idemKey)
      } else {
        entry = await api.post<EntryResponse>('/operations/cash-transfer', {
          client_id: client.id, currency_code: currencyCode, from_location_code: fromLocation,
          to_location_code: toLocationCt, amount, source_account_code: sourceAccount,
          execution_account_code: executionAccount, collection_account_code: collectionAccount,
          commission_currency: commissionCurrency, client_commission_amount: clientCommission,
          cost_commission_amount: costCommission, cost_correspondent_account_code: costCorrespondentAccount,
        }, idemKey)
      }
      resetForm()
      setSuccess(entry)
      onPosted(entry)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر الترحيل')
    } finally {
      setBusy(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape') {
      e.preventDefault()
      resetForm()
    } else if (e.key === 'Enter') {
      // Ctrl+Enter مقصودة أصلاً "حفظ وطباعة" (ج-٥) — الطباعة خارج نطاق
      // هذه المرحلة، فتُعامَل الآن كحفظ عادي بلا طباعة.
      e.preventDefault()
      if (!busy && client) void submit()
    }
  }

  return (
    <section className="journal-col journal-col-center">
      <div className="op-tabs">
        {TABS.map((t) => (
          <button key={t.id} type="button" className={`op-tab${tab === t.id ? ' is-active' : ''}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
        <button type="button" className="btn-text" style={{ marginInlineStart: 'auto' }} onClick={onOpenWizard}>
          معالج الخطوتين (دينار → دولار → رمبي)
        </button>
      </div>

      <div className="card op-form-card" onKeyDown={handleKeyDown}>
        {!client && <div className="alert alert-info">اختر عميلاً من العمود الأيمن أولاً</div>}

        {tab !== 'CASH_TRANSFER' && (
          <div className="op-row">
            <div className="field">
              <label className="field-label">العملة</label>
              <CurrencySelect value={currencyCode} onChange={(v) => { setCurrencyCode(v); setLocationCode('') }} currencies={currencies} />
            </div>
            <div className="field">
              <label className="field-label">الموقع</label>
              <LocationSelect value={locationCode} onChange={setLocationCode} locations={fromLocations} disabled={!currencyCode} />
            </div>
          </div>
        )}

        {tab === 'EXCHANGE' && (
          <div className="op-row">
            <div className="field">
              <label className="field-label">إلى عملة</label>
              <CurrencySelect
                value={toCurrency}
                onChange={(v) => { setToCurrency(v); setToLocation('') }}
                currencies={currencies.filter((c) => c.code === PIVOT_CODE || currencyCode === PIVOT_CODE)}
              />
            </div>
            <div className="field">
              <label className="field-label">إلى موقع</label>
              <LocationSelect value={toLocation} onChange={setToLocation} locations={toLocations} disabled={!toCurrency} />
            </div>
          </div>
        )}

        {(tab === 'RECEIPT' || tab === 'PAYMENT') && (
          <AccountSelect
            value={accountCode} onChange={setAccountCode} accounts={accounts}
            label={tab === 'RECEIPT' ? 'الحساب المستقبِل' : 'الحساب المصروف منه'}
          />
        )}

        {tab === 'CASH_TRANSFER' && (
          <>
            <div className="op-row">
              <div className="field">
                <label className="field-label">العملة</label>
                <CurrencySelect value={currencyCode} onChange={(v) => { setCurrencyCode(v); setFromLocation(''); setToLocationCt('') }} currencies={currencies} />
              </div>
              <div className="field">
                <label className="field-label">من موقع</label>
                <LocationSelect value={fromLocation} onChange={setFromLocation} locations={ctFromLocations} disabled={!currencyCode} />
              </div>
              <div className="field">
                <label className="field-label">إلى موقع</label>
                <LocationSelect value={toLocationCt} onChange={setToLocationCt} locations={ctToLocations} disabled={!currencyCode} />
              </div>
            </div>
            <AccountSelect value={sourceAccount} onChange={setSourceAccount} accounts={accounts} label="حساب المصدر (الشركة)" />
            <AccountSelect value={executionAccount} onChange={setExecutionAccount} accounts={accounts} label="الحساب المنفِّذ" />
            <AccountSelect value={collectionAccount} onChange={setCollectionAccount} accounts={accounts} label="حساب تحصيل العمولة" />
            <AccountSelect value={costCorrespondentAccount} onChange={setCostCorrespondentAccount} accounts={accounts} label="حساب تكلفة العمولة (المراسل)" />
            <div className="op-row">
              <div className="field">
                <label className="field-label">عملة العمولة</label>
                <CurrencySelect value={commissionCurrency} onChange={setCommissionCurrency} currencies={currencies} />
              </div>
              <div className="field">
                <label className="field-label">عمولة العميل</label>
                <input className="num" value={clientCommission} onChange={(e) => setClientCommission(e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">تكلفة العمولة</label>
                <input className="num" value={costCommission} onChange={(e) => setCostCommission(e.target.value)} />
              </div>
            </div>
          </>
        )}

        <div className="op-row">
          <div className="field field-amount">
            <label className="field-label">المبلغ</label>
            <input className="num" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </div>
          {tab === 'EXCHANGE' && (
            <>
              <div className="field field-rate">
                <label className="field-label">سعر العميل</label>
                <input className="num" value={clientRate} onChange={(e) => setClientRate(e.target.value)} />
              </div>
              <div className="field field-rate">
                <label className="field-label">سعر التكلفة</label>
                <input className="num" value={costRate} onChange={(e) => setCostRate(e.target.value)} />
                <span className="rate-hint">سعر التكلفة داخلي — لا يظهر للعميل أبداً</span>
              </div>
            </>
          )}
        </div>

        {tab === 'EXCHANGE' && exchangePreview && (
          <div className="result-card">
            <div className="result-row"><span>المبلغ الناتج للعميل</span><span className="num">{exchangePreview.clientAmt.toString()} {toCurrency}</span></div>
            <div className="result-row result-dashed"><span>مبلغ التكلفة (داخلي)</span><span className="num text-muted">{exchangePreview.costAmt.toString()} {toCurrency}</span></div>
            <div className="result-row result-final">
              <span>ربح العملية</span>
              <span className={`num ${exchangePreview.diff.gte(0) ? 'money-positive' : 'money-negative'}`}>
                {exchangePreview.diff.toString()} {toCurrency}
              </span>
            </div>
          </div>
        )}

        {tab === 'EXCHANGE' && exchangePreview && exchangePreview.diff.lt(0) && (
          <div className="field">
            <label className="field-label">سبب الهامش السالب (إلزامي)</label>
            <input value={negativeMarginReason} onChange={(e) => setNegativeMarginReason(e.target.value)} />
          </div>
        )}

        {error && <div className="alert alert-critical">{error}</div>}
        {success && (
          <div className="alert alert-info">
            تم الترحيل — {success.entry_no}
            {success.profit_amount && ` — ربح ${success.profit_amount} ${success.profit_currency}`}
          </div>
        )}

        <div className="op-shortcuts">
          <span className="kbd-chip">Enter حفظ وترحيل</span>
          <span className="kbd-chip">Ctrl+Enter حفظ وطباعة</span>
          <span className="kbd-chip">Esc إلغاء</span>
        </div>

        <button type="button" className="btn btn-primary btn-lg" style={{ width: '100%' }} disabled={busy || !client} onClick={submit}>
          حفظ وترحيل
        </button>
      </div>
    </section>
  )
}
