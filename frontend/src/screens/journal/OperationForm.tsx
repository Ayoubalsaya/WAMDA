import { useEffect, useMemo, useState } from 'react'
import { api, ApiError, newIdempotencyKey } from '../../api/client'
import type {
  AccountRef, Beneficiary, ClientBalance, ClientSearchResult, Currency, EntryResponse, Location,
  PendingSwiftMovement,
} from '../../api/types'
import { PIVOT_CODE, convertPreview, roundCollectedFromClient, roundGivenToClient, roundInternal } from '../../lib/fxPreview'
import { useReferenceData } from '../../hooks/useReferenceData'
import { useAccountsForOperation, type AccountFieldSpec } from '../../hooks/useAccountsForOperation'

type OpTab =
  | 'RECEIPT' | 'PAYMENT' | 'EXCHANGE' | 'CASH_TRANSFER' | 'REMIT_OUT' | 'EXPENSE'
  | 'SWIFT_OUT' | 'SWIFT_IN' | 'SWIFT_RETURN' | 'LOCAL_MOVE' | 'OPENING' | 'ADJUSTMENT'

// ج-٣: ١٢ عملية في مستويين — الأول يغطي أكثر من ٩٠٪ من الحركة اليومية
const LEVEL1: { id: OpTab; label: string }[] = [
  { id: 'RECEIPT', label: 'قبض' },
  { id: 'PAYMENT', label: 'صرف' },
  { id: 'EXCHANGE', label: 'صرافة' },
  { id: 'CASH_TRANSFER', label: 'تحويل بعمولة' },
  { id: 'REMIT_OUT', label: 'إرسال لمستفيد' },
  { id: 'EXPENSE', label: 'مصروف' },
]
const LEVEL2: { id: OpTab; label: string }[] = [
  { id: 'SWIFT_OUT', label: 'سويفت خروج' },
  { id: 'SWIFT_IN', label: 'سويفت وصول' },
  { id: 'SWIFT_RETURN', label: 'سويفت مرتجع' },
  { id: 'LOCAL_MOVE', label: 'نقل داخلي' },
  { id: 'OPENING', label: 'رصيد افتتاحي' },
  { id: 'ADJUSTMENT', label: 'تسوية' },
]
const ALL_TABS = [...LEVEL1, ...LEVEL2]

// العمليات التي تمسّ حساب عميل مباشرة — البقية تخصّ الشركة/الشريك وحدها
const REQUIRES_CLIENT = new Set<OpTab>(['RECEIPT', 'PAYMENT', 'EXCHANGE', 'CASH_TRANSFER', 'REMIT_OUT', 'SWIFT_RETURN'])
const ADMIN_ONLY_TABS = new Set<OpTab>(['OPENING', 'ADJUSTMENT'])

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

function AccountSelect({
  value, onChange, accounts, label, emptyMessage,
}: { value: string; onChange: (v: string) => void; accounts: AccountRef[]; label: string; emptyMessage?: string }) {
  return (
    <div className="field">
      <label className="field-label">{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={accounts.length === 0}>
        <option value="" disabled>{accounts.length ? 'اختر حساباً' : (emptyMessage ?? 'لا حسابات مطابقة')}</option>
        {accounts.map((a) => <option key={a.code} value={a.code}>{a.code} — {a.name_ar}</option>)}
      </select>
      {accounts.length === 0 && emptyMessage && <span className="rate-hint">{emptyMessage}</span>}
    </div>
  )
}

interface OperationFormProps {
  client: ClientSearchResult | null
  currentUserRole: 'ADMIN' | 'ACCOUNTANT'
  onPosted: (entry: EntryResponse) => void
  onOpenWizard: () => void
  requestedTab?: string | null
}

export function OperationForm({ client, currentUserRole, onPosted, onOpenWizard, requestedTab }: OperationFormProps) {
  const { currencies, accounts, locationsForCurrency } = useReferenceData()
  const [tab, setTab] = useState<OpTab>('RECEIPT')
  const [moreOpen, setMoreOpen] = useState(false)
  const [idemKey, setIdemKey] = useState(newIdempotencyKey())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<EntryResponse | null>(null)

  // حقول العمليات الأربع الأصلية (المرحلة ٥) — بلا تغيير
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

  // حقول الثماني عمليات الجديدة (المرحلة ٧) — كائن عام واحد، أبسط من
  // إضافة ٣٠+ useState فردياً لكل حقل من كل عملية
  const [fields, setFields] = useState<Record<string, string>>({})
  const setField = (key: string, value: string) => setFields((f) => ({ ...f, [key]: value }))

  const [beneficiaries, setBeneficiaries] = useState<Beneficiary[]>([])
  const [pendingSwift, setPendingSwift] = useState<PendingSwiftMovement[]>([])
  const [openingAccountMode, setOpeningAccountMode] = useState<'system' | 'client'>('system')
  const [clientBalancesForOpening, setClientBalancesForOpening] = useState<ClientBalance[]>([])

  function resetForm() {
    setCurrencyCode(''); setLocationCode(''); setAmount(''); setAccountCode('')
    setToCurrency(''); setToLocation(''); setCostRate(''); setClientRate(''); setNegativeMarginReason('')
    setFromLocation(''); setToLocationCt(''); setCommissionCurrency('')
    setClientCommission(''); setCostCommission(''); setSourceAccount(''); setExecutionAccount('')
    setCollectionAccount(''); setCostCorrespondentAccount('')
    setFields({})
    setOpeningAccountMode('system')
    setIdemKey(newIdempotencyKey())
    setSuccess(null)
  }

  useEffect(() => { resetForm() }, [tab])

  useEffect(() => {
    if (requestedTab && ALL_TABS.some((t) => t.id === requestedTab)) {
      setTab(requestedTab as OpTab)
      if (LEVEL2.some((t) => t.id === requestedTab)) setMoreOpen(true)
    }
  }, [requestedTab])

  // مستفيدو العميل النشطون — لازمون لـREMIT_OUT
  useEffect(() => {
    if (tab !== 'REMIT_OUT' || !client) {
      setBeneficiaries([])
      return
    }
    let cancelled = false
    void api.get<Beneficiary[]>(`/clients/${client.id}/beneficiaries`).then((rows) => {
      if (!cancelled) setBeneficiaries(rows)
    })
    return () => { cancelled = true }
  }, [tab, client])

  // حركات سويفت معلَّقة — لازمة لـSWIFT_IN/SWIFT_RETURN
  useEffect(() => {
    if (tab !== 'SWIFT_IN' && tab !== 'SWIFT_RETURN') {
      setPendingSwift([])
      return
    }
    let cancelled = false
    void api.get<PendingSwiftMovement[]>('/reference/swift-movements/pending').then((rows) => {
      if (!cancelled) setPendingSwift(rows)
    })
    return () => { cancelled = true }
  }, [tab])

  // أرصدة العميل المختار — لازمة لوضع "حساب عميل" في OPENING
  useEffect(() => {
    if (tab !== 'OPENING' || openingAccountMode !== 'client' || !client) {
      setClientBalancesForOpening([])
      return
    }
    let cancelled = false
    void api.get<ClientBalance[]>(`/clients/${client.id}/balances`).then((rows) => {
      if (!cancelled) setClientBalancesForOpening(rows)
    })
    return () => { cancelled = true }
  }, [tab, openingAccountMode, client])

  const fromLocations = useMemo(() => locationsForCurrency(currencyCode), [currencyCode, locationsForCurrency])
  const toLocations = useMemo(() => locationsForCurrency(toCurrency), [toCurrency, locationsForCurrency])
  const ctFromLocations = useMemo(() => locationsForCurrency(currencyCode), [currencyCode, locationsForCurrency])
  const ctToLocations = useMemo(() => locationsForCurrency(currencyCode), [currencyCode, locationsForCurrency])
  const remitLocations = useMemo(() => locationsForCurrency(PIVOT_CODE), [locationsForCurrency])
  const expenseAccounts = useMemo(() => accounts.filter((a) => a.type === 'EXPENSE'), [accounts])

  // حسابات مُصفّاة بحسب (نوع العملية × دور الحقل × العملة × الموقع) عبر
  // /reference/accounts/for-operation — بديل `accounts` غير المُصفّى الذي
  // كان يعرض شجرة الحسابات كاملة لكل حقل بلا استثناء. spec=null يعني
  // "هذا الحقل غير معني بالتبويب الحالي" فلا يُطلَق أي جلب.
  const receivingPayingSpec: AccountFieldSpec | null =
    tab === 'RECEIPT' || tab === 'PAYMENT'
      ? { operationType: tab, field: tab === 'RECEIPT' ? 'receiving' : 'paying', currencyCode, locationCode: locationCode || undefined }
      : null
  const { accounts: receivingPayingAccounts } = useAccountsForOperation(receivingPayingSpec)

  const ctSourceSpec: AccountFieldSpec | null =
    tab === 'CASH_TRANSFER' ? { operationType: 'CASH_TRANSFER', field: 'source', currencyCode, locationCode: fromLocation || undefined } : null
  const { accounts: ctSourceAccounts } = useAccountsForOperation(ctSourceSpec)

  const ctExecutionSpec: AccountFieldSpec | null =
    tab === 'CASH_TRANSFER' ? { operationType: 'CASH_TRANSFER', field: 'execution', currencyCode, locationCode: toLocationCt || undefined } : null
  const { accounts: ctExecutionAccounts } = useAccountsForOperation(ctExecutionSpec)

  const ctCollectionSpec: AccountFieldSpec | null =
    tab === 'CASH_TRANSFER' ? { operationType: 'CASH_TRANSFER', field: 'collection', currencyCode: commissionCurrency, locationCode: toLocationCt || undefined } : null
  const { accounts: ctCollectionAccounts } = useAccountsForOperation(ctCollectionSpec)

  const ctCostCorrespondentSpec: AccountFieldSpec | null =
    tab === 'CASH_TRANSFER' ? { operationType: 'CASH_TRANSFER', field: 'cost_correspondent', currencyCode: commissionCurrency, locationCode: toLocationCt || undefined } : null
  const { accounts: ctCostCorrespondentAccounts } = useAccountsForOperation(ctCostCorrespondentSpec)

  const localMoveFromSpec: AccountFieldSpec | null =
    tab === 'LOCAL_MOVE' ? { operationType: 'LOCAL_MOVE', field: 'from', currencyCode: fields.currency_code ?? '' } : null
  const { accounts: localMoveFromAccounts } = useAccountsForOperation(localMoveFromSpec)

  const localMoveToSpec: AccountFieldSpec | null =
    tab === 'LOCAL_MOVE' ? { operationType: 'LOCAL_MOVE', field: 'to', currencyCode: fields.currency_code ?? '' } : null
  const { accounts: localMoveToAccounts } = useAccountsForOperation(localMoveToSpec)

  const swiftOutPartnerSpec: AccountFieldSpec | null =
    tab === 'SWIFT_OUT' ? { operationType: 'SWIFT_OUT', field: 'partner', currencyCode: PIVOT_CODE } : null
  const { accounts: swiftOutPartnerAccounts } = useAccountsForOperation(swiftOutPartnerSpec)

  // عملة الاستقبال تتبع وجود سعر تحويل البنك: بلا سعر = إيداع دولار مباشر،
  // بسعر = فتح دفعة رمبي (انظر الشارة الديناميكية أدناه) — نفس المنطق هنا.
  const swiftInCurrency = fields.bank_conversion_rate ? 'CNY' : PIVOT_CODE
  const swiftInReceivingSpec: AccountFieldSpec | null =
    tab === 'SWIFT_IN' ? { operationType: 'SWIFT_IN', field: 'receiving', currencyCode: swiftInCurrency } : null
  const { accounts: swiftInReceivingAccounts } = useAccountsForOperation(swiftInReceivingSpec)

  const remitOutPartnerSpec: AccountFieldSpec | null =
    tab === 'REMIT_OUT' ? { operationType: 'REMIT_OUT', field: 'partner', currencyCode: PIVOT_CODE, locationCode: fields.from_location_code || undefined } : null
  const { accounts: remitOutPartnerAccounts } = useAccountsForOperation(remitOutPartnerSpec)

  const expensePayingSpec: AccountFieldSpec | null =
    tab === 'EXPENSE' ? { operationType: 'EXPENSE', field: 'paying', currencyCode: fields.currency_code ?? '' } : null
  const { accounts: expensePayingAccounts } = useAccountsForOperation(expensePayingSpec)

  const selectedBeneficiary = beneficiaries.find((b) => b.id === Number(fields.beneficiary_id))
  const selectedReturnMovement = pendingSwift.find((m) => m.id === Number(fields.swift_movement_id))

  // معاينة فورية — decimal.js في المتصفح فقط، السيرفر يعيد الحساب ويحسم
  const exchangePreview = useMemo(() => {
    if (tab !== 'EXCHANGE' || !currencyCode || !toCurrency || !amount) return null
    const toCcy = currencies.find((c) => c.code === toCurrency)
    if (!toCcy) return null
    const clientRaw = convertPreview(amount, clientRate, currencyCode)
    const costRaw = convertPreview(amount, costRate, currencyCode)
    const clientAmt = roundGivenToClient(clientRaw, toCcy.decimals)
    const costAmt = roundInternal(costRaw, toCcy.decimals)
    return { clientAmt, costAmt, diff: costAmt.minus(clientAmt) }
  }, [tab, currencyCode, toCurrency, amount, clientRate, costRate, currencies])

  // §٤ رقم ٩: موجب = ربح (العميل دفع أكثر من التكلفة) — عكس إشارة الصرافة تماماً
  const remitPreview = useMemo(() => {
    if (tab !== 'REMIT_OUT' || !selectedBeneficiary || !fields.beneficiary_amount) return null
    const usd = currencies.find((c) => c.code === PIVOT_CODE)
    if (!usd) return null
    const clientRaw = convertPreview(fields.beneficiary_amount, fields.client_rate ?? '', selectedBeneficiary.currency_code)
    const costRaw = convertPreview(fields.beneficiary_amount, fields.cost_rate ?? '', selectedBeneficiary.currency_code)
    const clientAmt = roundCollectedFromClient(clientRaw, usd.decimals)
    const costAmt = roundInternal(costRaw, usd.decimals)
    return { clientAmt, costAmt, diff: clientAmt.minus(costAmt) }
  }, [tab, selectedBeneficiary, fields.beneficiary_amount, fields.client_rate, fields.cost_rate, currencies])

  async function submit(printAfter = false) {
    const needsClient = REQUIRES_CLIENT.has(tab)
    if (needsClient && !client) {
      setError('اختر عميلاً أولاً')
      return
    }
    setBusy(true)
    setError(null)
    try {
      let entry: EntryResponse
      if (tab === 'RECEIPT') {
        entry = await api.post<EntryResponse>('/operations/receipt', {
          client_id: client!.id, currency_code: currencyCode, location_code: locationCode,
          amount, receiving_account_code: accountCode,
        }, idemKey)
      } else if (tab === 'PAYMENT') {
        entry = await api.post<EntryResponse>('/operations/payment', {
          client_id: client!.id, currency_code: currencyCode, location_code: locationCode,
          amount, paying_account_code: accountCode,
        }, idemKey)
      } else if (tab === 'EXCHANGE') {
        entry = await api.post<EntryResponse>('/operations/exchange', {
          client_id: client!.id, from_currency: currencyCode, from_location_code: locationCode,
          to_currency: toCurrency, to_location_code: toLocation, amount, cost_rate: costRate,
          client_rate: clientRate, negative_margin_reason: negativeMarginReason || undefined,
        }, idemKey)
      } else if (tab === 'CASH_TRANSFER') {
        entry = await api.post<EntryResponse>('/operations/cash-transfer', {
          client_id: client!.id, currency_code: currencyCode, from_location_code: fromLocation,
          to_location_code: toLocationCt, amount, source_account_code: sourceAccount,
          execution_account_code: executionAccount, collection_account_code: collectionAccount,
          commission_currency: commissionCurrency, client_commission_amount: clientCommission,
          cost_commission_amount: costCommission, cost_correspondent_account_code: costCorrespondentAccount,
        }, idemKey)
      } else if (tab === 'REMIT_OUT') {
        entry = await api.post<EntryResponse>('/operations/remit-out', {
          client_id: client!.id, from_location_code: fields.from_location_code,
          partner_account_code: fields.partner_account_code, beneficiary_id: Number(fields.beneficiary_id),
          beneficiary_amount: fields.beneficiary_amount, cost_rate: fields.cost_rate, client_rate: fields.client_rate,
          purpose: fields.purpose || undefined, negative_margin_reason: fields.negative_margin_reason || undefined,
        }, idemKey)
      } else if (tab === 'EXPENSE') {
        entry = await api.post<EntryResponse>('/operations/expense', {
          expense_account_code: fields.expense_account_code, currency_code: fields.currency_code,
          paying_account_code: fields.paying_account_code, amount: fields.amount, description: fields.description,
        }, idemKey)
      } else if (tab === 'SWIFT_OUT') {
        entry = await api.post<EntryResponse>('/operations/swift-out', {
          partner_account_code: fields.partner_account_code, amount: fields.amount,
          external_ref: fields.external_ref || undefined, description: fields.description || undefined,
        }, idemKey)
      } else if (tab === 'SWIFT_IN') {
        entry = await api.post<EntryResponse>('/operations/swift-in', {
          swift_movement_id: Number(fields.swift_movement_id), total_amount: fields.total_amount,
          fee_amount: fields.fee_amount || '0', receiving_account_code: fields.receiving_account_code,
          bank_conversion_rate: fields.bank_conversion_rate || undefined,
        }, idemKey)
      } else if (tab === 'SWIFT_RETURN') {
        // partner_account_code مُشتقّ من الحركة نفسها — لا اختيار يدوي (انظر التعليق في JSX)
        entry = await api.post<EntryResponse>('/operations/swift-return', {
          swift_movement_id: Number(fields.swift_movement_id), partner_account_code: selectedReturnMovement?.partner_account_code,
          total_amount: fields.total_amount, client_id: client!.id, client_location_code: fields.client_location_code,
          return_fee_amount: fields.return_fee_amount || '0',
        }, idemKey)
      } else if (tab === 'LOCAL_MOVE') {
        entry = await api.post<EntryResponse>('/operations/local-move', {
          currency_code: fields.currency_code, from_account_code: fields.from_account_code,
          to_account_code: fields.to_account_code, amount: fields.amount, fee_amount: fields.fee_amount || '0',
        }, idemKey)
      } else if (tab === 'OPENING') {
        entry = await api.post<EntryResponse>('/operations/opening', {
          account_code: fields.account_code, currency_code: fields.currency_code, amount: fields.amount,
          is_debit: fields.is_debit === 'true', as_of_date: fields.as_of_date, source_type: fields.source_type,
          confidence: fields.confidence, source_note: fields.source_note || undefined,
        }, idemKey)
      } else {
        entry = await api.post<EntryResponse>('/operations/adjustment', {
          account_code: fields.account_code, currency_code: fields.currency_code, amount: fields.amount,
          is_debit: fields.is_debit === 'true', reason: fields.reason,
        }, idemKey)
      }
      resetForm()
      setSuccess(entry)
      onPosted(entry)
      if (printAfter) window.print()
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
      e.preventDefault()
      if (!busy) void submit(e.ctrlKey)
    }
  }

  const needsClient = REQUIRES_CLIENT.has(tab)
  const adminBlocked = ADMIN_ONLY_TABS.has(tab) && currentUserRole !== 'ADMIN'

  return (
    <section className="journal-col journal-col-center">
      <div className="op-tabs">
        {LEVEL1.map((t) => (
          <button key={t.id} type="button" className={`op-tab${tab === t.id ? ' is-active' : ''}`} onClick={() => { setTab(t.id); setMoreOpen(false) }}>
            {t.label}
          </button>
        ))}
        <button type="button" className={`op-tab${moreOpen ? ' is-active' : ''}`} onClick={() => setMoreOpen((v) => !v)}>
          المزيد
        </button>
        <button type="button" className="btn-text" style={{ marginInlineStart: 'auto' }} onClick={onOpenWizard}>
          معالج الخطوتين (دينار → دولار → رمبي)
        </button>
      </div>

      {moreOpen && (
        <div className="op-tabs" style={{ marginBottom: 12 }}>
          {LEVEL2.map((t) => (
            <button key={t.id} type="button" className={`op-tab${tab === t.id ? ' is-active' : ''}`} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
      )}

      <div className="card op-form-card" onKeyDown={handleKeyDown}>
        {needsClient && !client && <div className="alert alert-info">اختر عميلاً من العمود الأيمن أولاً</div>}
        {adminBlocked && <div className="alert alert-warning">هذه العملية تتطلب صلاحية مدير — لن يقبلها الخادم لدورك الحالي.</div>}

        {tab !== 'CASH_TRANSFER' && (tab === 'RECEIPT' || tab === 'PAYMENT' || tab === 'EXCHANGE') && (
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
            value={accountCode} onChange={setAccountCode} accounts={receivingPayingAccounts}
            label={tab === 'RECEIPT' ? 'الحساب المستقبِل' : 'الحساب المصروف منه'}
            emptyMessage={!currencyCode || !locationCode ? 'اختر العملة والموقع أولاً' : 'لا حسابات صناديق/مراسلين/بنوك بهذه العملة والموقع'}
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
                <label className="field-label">إلى موقع (يشمل بنغازي — عمولة فرق دائماً)</label>
                <LocationSelect value={toLocationCt} onChange={setToLocationCt} locations={ctToLocations} disabled={!currencyCode} />
              </div>
            </div>
            <AccountSelect
              value={sourceAccount} onChange={setSourceAccount} accounts={ctSourceAccounts} label="حساب المصدر (الشركة)"
              emptyMessage={!currencyCode || !fromLocation ? 'اختر العملة وموقع المصدر أولاً' : 'لا صناديق/بنوك بهذه العملة في موقع المصدر'}
            />
            <AccountSelect
              value={executionAccount} onChange={setExecutionAccount} accounts={ctExecutionAccounts} label="الحساب المنفِّذ"
              emptyMessage={!currencyCode || !toLocationCt ? 'اختر العملة وموقع الوجهة أولاً' : 'لا صناديق/بنوك بهذه العملة في موقع الوجهة'}
            />
            <AccountSelect
              value={collectionAccount} onChange={setCollectionAccount} accounts={ctCollectionAccounts} label="حساب تحصيل العمولة"
              emptyMessage={!commissionCurrency || !toLocationCt ? 'اختر عملة العمولة وموقع الوجهة أولاً' : 'لا صناديق/بنوك بعملة العمولة في موقع الوجهة'}
            />
            <AccountSelect
              value={costCorrespondentAccount} onChange={setCostCorrespondentAccount} accounts={ctCostCorrespondentAccounts} label="حساب تكلفة العمولة (المراسل)"
              emptyMessage={!commissionCurrency || !toLocationCt ? 'اختر عملة العمولة وموقع الوجهة أولاً' : 'لا حسابات مراسلين بعملة العمولة في موقع الوجهة'}
            />
            <div className="op-row">
              <div className="field">
                <label className="field-label">عملة العمولة</label>
                <CurrencySelect value={commissionCurrency} onChange={setCommissionCurrency} currencies={currencies} />
              </div>
              <div className="field">
                <label className="field-label">عمولة العميل (تحصيل)</label>
                <input className="num" value={clientCommission} onChange={(e) => setClientCommission(e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">تكلفة العمولة</label>
                <input className="num" value={costCommission} onChange={(e) => setCostCommission(e.target.value)} />
              </div>
            </div>
          </>
        )}

        {tab === 'REMIT_OUT' && (
          <>
            <div className="op-row">
              <div className="field">
                <label className="field-label">الموقع المخصوم من العميل</label>
                <LocationSelect value={fields.from_location_code ?? ''} onChange={(v) => setField('from_location_code', v)} locations={remitLocations} />
              </div>
              <AccountSelect
                value={fields.partner_account_code ?? ''} onChange={(v) => setField('partner_account_code', v)}
                accounts={remitOutPartnerAccounts} label="حساب المراسل"
                emptyMessage={!fields.from_location_code ? 'اختر الموقع المخصوم أولاً' : 'لا حسابات مراسلين بالدولار في هذا الموقع'}
              />
            </div>
            <div className="field">
              <label className="field-label">المستفيد (من السجل — إلزامي)</label>
              <select value={fields.beneficiary_id ?? ''} onChange={(e) => setField('beneficiary_id', e.target.value)}>
                <option value="" disabled>{client ? 'اختر مستفيداً' : 'اختر عميلاً أولاً'}</option>
                {beneficiaries.map((b) => (
                  <option key={b.id} value={b.id}>{b.name} — {b.account_number} ({b.currency_code})</option>
                ))}
              </select>
              {client && beneficiaries.length === 0 && (
                <span className="rate-hint">لا مستفيدون نشطون لهذا العميل — أضِف مستفيداً من صفحة العميل أولاً</span>
              )}
            </div>
            <div className="op-row">
              <div className="field field-amount">
                <label className="field-label">مبلغ المستفيد ({selectedBeneficiary?.currency_code ?? '—'})</label>
                <input className="num" value={fields.beneficiary_amount ?? ''} onChange={(e) => setField('beneficiary_amount', e.target.value)} />
              </div>
              <div className="field field-rate">
                <label className="field-label">سعر العميل</label>
                <input className="num" value={fields.client_rate ?? ''} onChange={(e) => setField('client_rate', e.target.value)} />
              </div>
              <div className="field field-rate">
                <label className="field-label">سعر التكلفة</label>
                <input className="num" value={fields.cost_rate ?? ''} onChange={(e) => setField('cost_rate', e.target.value)} />
                <span className="rate-hint">سعر التكلفة داخلي — لا يظهر للعميل أبداً</span>
              </div>
            </div>
            <div className="field">
              <label className="field-label">الغرض (اختياري)</label>
              <input value={fields.purpose ?? ''} onChange={(e) => setField('purpose', e.target.value)} />
            </div>
            {remitPreview && (
              <div className="result-card">
                <div className="result-row"><span>يُحصَّل من العميل</span><span className="num">{remitPreview.clientAmt.toString()} USD</span></div>
                <div className="result-row result-dashed"><span>التكلفة (داخلي)</span><span className="num text-muted">{remitPreview.costAmt.toString()} USD</span></div>
                <div className="result-row result-final">
                  <span>ربح العملية</span>
                  <span className={`num ${remitPreview.diff.gte(0) ? 'money-positive' : 'money-negative'}`}>{remitPreview.diff.toString()} USD</span>
                </div>
              </div>
            )}
            {remitPreview && remitPreview.diff.lt(0) && (
              <div className="field">
                <label className="field-label">سبب الهامش السالب (إلزامي)</label>
                <input value={fields.negative_margin_reason ?? ''} onChange={(e) => setField('negative_margin_reason', e.target.value)} />
              </div>
            )}
          </>
        )}

        {tab === 'EXPENSE' && (
          <>
            <div className="op-row">
              <AccountSelect value={fields.expense_account_code ?? ''} onChange={(v) => setField('expense_account_code', v)} accounts={expenseAccounts} label="بند المصروف" />
              <div className="field">
                <label className="field-label">العملة</label>
                <CurrencySelect value={fields.currency_code ?? ''} onChange={(v) => setField('currency_code', v)} currencies={currencies} />
              </div>
            </div>
            <AccountSelect
              value={fields.paying_account_code ?? ''} onChange={(v) => setField('paying_account_code', v)} accounts={expensePayingAccounts} label="الحساب المصروف منه"
              emptyMessage={!fields.currency_code ? 'اختر العملة أولاً' : 'لا صناديق/بنوك بهذه العملة'}
            />
            <div className="op-row">
              <div className="field field-amount">
                <label className="field-label">المبلغ</label>
                <input className="num" value={fields.amount ?? ''} onChange={(e) => setField('amount', e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">البيان (إلزامي)</label>
                <input value={fields.description ?? ''} onChange={(e) => setField('description', e.target.value)} />
              </div>
            </div>
          </>
        )}

        {tab === 'SWIFT_OUT' && (
          <>
            <AccountSelect
              value={fields.partner_account_code ?? ''} onChange={(v) => setField('partner_account_code', v)} accounts={swiftOutPartnerAccounts} label="حساب المراسل (تركيا)"
              emptyMessage="لا حسابات مراسلين بالدولار في تركيا — سجّل الشريك من شاشة الشركاء أولاً"
            />
            <div className="op-row">
              <div className="field field-amount">
                <label className="field-label">المبلغ (USD)</label>
                <input className="num" value={fields.amount ?? ''} onChange={(e) => setField('amount', e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">مرجع خارجي (اختياري)</label>
                <input className="num" value={fields.external_ref ?? ''} onChange={(e) => setField('external_ref', e.target.value)} />
              </div>
            </div>
          </>
        )}

        {tab === 'SWIFT_IN' && (
          <>
            <div className="field">
              <label className="field-label">الحركة المعلَّقة (أُرسلت ولم تُستقبَل بعد)</label>
              <select value={fields.swift_movement_id ?? ''} onChange={(e) => setField('swift_movement_id', e.target.value)}>
                <option value="" disabled>{pendingSwift.length ? 'اختر حركة' : 'لا حركات معلَّقة'}</option>
                {pendingSwift.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.out_entry_no ?? m.id} — {m.amount} {m.currency_code} — {m.partner_name_ar ?? 'مراسل'}
                  </option>
                ))}
              </select>
            </div>
            <div className="op-row">
              <div className="field field-amount">
                <label className="field-label">المبلغ الواصل</label>
                <input className="num" value={fields.total_amount ?? ''} onChange={(e) => setField('total_amount', e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">الرسوم الفعلية</label>
                <input className="num" value={fields.fee_amount ?? ''} onChange={(e) => setField('fee_amount', e.target.value)} />
              </div>
            </div>
            <AccountSelect
              value={fields.receiving_account_code ?? ''} onChange={(v) => setField('receiving_account_code', v)} accounts={swiftInReceivingAccounts} label="الحساب المستقبِل"
              emptyMessage={`لا بنوك صينية بعملة ${swiftInCurrency} — سجّل البنك من شاشة الشركاء أولاً`}
            />
            <div className="field">
              <label className="field-label">سعر تحويل البنك للرمبي (اختياري)</label>
              <input className="num" value={fields.bank_conversion_rate ?? ''} onChange={(e) => setField('bank_conversion_rate', e.target.value)} />
              <span className="rate-hint">
                {fields.bank_conversion_rate
                  ? 'سيُفتَح دفعة رمبي جديدة تلقائياً بهذا السعر عند الترحيل'
                  : 'بلا سعر — إيداع دولار مباشر بلا فتح دفعة'}
              </span>
            </div>
          </>
        )}

        {tab === 'SWIFT_RETURN' && (
          <>
            <div className="field">
              <label className="field-label">الحركة المعلَّقة المطلوب ارتجاعها</label>
              <select value={fields.swift_movement_id ?? ''} onChange={(e) => setField('swift_movement_id', e.target.value)}>
                <option value="" disabled>{pendingSwift.length ? 'اختر حركة' : 'لا حركات معلَّقة'}</option>
                {pendingSwift.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.out_entry_no ?? m.id} — {m.amount} {m.currency_code} — {m.partner_name_ar ?? 'مراسل'}
                  </option>
                ))}
              </select>
              {/* بلا حقل اختيار حساب مراسل إطلاقاً — يُشتق آلياً من partner_account_code
                  الذي تحمله الحركة المختارة نفسها (انظر submit()). أي اختيار
                  يدوي هنا خطر حقيقي: قد يُعيد المال لمراسل خاطئ. */}
              {fields.swift_movement_id && (
                <span className="rate-hint">
                  حساب المراسل يُشتق تلقائياً من الحركة المختارة: {selectedReturnMovement?.partner_account_code ?? '—'}
                </span>
              )}
            </div>
            <div className="op-row">
              <div className="field field-amount">
                <label className="field-label">المبلغ المرتجع كاملاً</label>
                <input className="num" value={fields.total_amount ?? ''} onChange={(e) => setField('total_amount', e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">رسوم على العميل</label>
                <input className="num" value={fields.return_fee_amount ?? ''} onChange={(e) => setField('return_fee_amount', e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">موقع العميل</label>
                <LocationSelect value={fields.client_location_code ?? ''} onChange={(v) => setField('client_location_code', v)} locations={remitLocations} />
              </div>
            </div>
          </>
        )}

        {tab === 'LOCAL_MOVE' && (
          <>
            <div className="alert alert-info">نقل داخلي بين حسابات الشركة فقط — لا يمسّ أي حساب عميل إطلاقاً.</div>
            <div className="field">
              <label className="field-label">العملة</label>
              <CurrencySelect value={fields.currency_code ?? ''} onChange={(v) => setField('currency_code', v)} currencies={currencies} />
            </div>
            <div className="op-row">
              <AccountSelect
                value={fields.from_account_code ?? ''} onChange={(v) => setField('from_account_code', v)} accounts={localMoveFromAccounts} label="من حساب"
                emptyMessage={!fields.currency_code ? 'اختر العملة أولاً' : 'لا حسابات شركة بهذه العملة'}
              />
              <AccountSelect
                value={fields.to_account_code ?? ''} onChange={(v) => setField('to_account_code', v)} accounts={localMoveToAccounts} label="إلى حساب"
                emptyMessage={!fields.currency_code ? 'اختر العملة أولاً' : 'لا حسابات شركة بهذه العملة'}
              />
            </div>
            <div className="op-row">
              <div className="field field-amount">
                <label className="field-label">المبلغ</label>
                <input className="num" value={fields.amount ?? ''} onChange={(e) => setField('amount', e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">رسوم (اختياري — تُقيَّد في 5200)</label>
                <input className="num" value={fields.fee_amount ?? ''} onChange={(e) => setField('fee_amount', e.target.value)} />
              </div>
            </div>
          </>
        )}

        {tab === 'OPENING' && (
          <>
            <div className="op-row">
              <label className="field-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="radio" name="opening-mode" checked={openingAccountMode === 'system'} onChange={() => setOpeningAccountMode('system')} />
                حساب نظامي
              </label>
              <label className="field-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="radio" name="opening-mode" checked={openingAccountMode === 'client'} onChange={() => setOpeningAccountMode('client')} disabled={!client} />
                حساب عميل {!client && '(اختر عميلاً من العمود الأيمن أولاً)'}
              </label>
            </div>
            {openingAccountMode === 'system' ? (
              // استثناء مقصود — لا تصفية عبر /reference/accounts/for-operation هنا:
              // رصيد افتتاحي قد يمسّ أي حساب في الشجرة، فتضييق الاختيار كان
              // سيمنع حالات مشروعة لا يمكن حصرها مسبقاً (انظر توثيق الاستثناء
              // الكامل في app/engine/account_filters.py).
              <AccountSelect value={fields.account_code ?? ''} onChange={(v) => setField('account_code', v)} accounts={accounts} label="الحساب" />
            ) : (
              <div className="field">
                <label className="field-label">حساب العميل (يجب أن يكون موجوداً فعلاً)</label>
                <select value={fields.account_code ?? ''} onChange={(e) => setField('account_code', e.target.value)}>
                  <option value="" disabled>{clientBalancesForOpening.length ? 'اختر حساباً' : 'لا حسابات بعد لهذا العميل'}</option>
                  {clientBalancesForOpening.map((b) => (
                    <option key={b.account_code} value={b.account_code}>{b.currency_code} — {b.location_code} ({b.account_code})</option>
                  ))}
                </select>
              </div>
            )}
            <div className="op-row">
              <div className="field">
                <label className="field-label">العملة</label>
                <CurrencySelect value={fields.currency_code ?? ''} onChange={(v) => setField('currency_code', v)} currencies={currencies} />
              </div>
              <div className="field field-amount">
                <label className="field-label">المبلغ</label>
                <input className="num" value={fields.amount ?? ''} onChange={(e) => setField('amount', e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label">التاريخ (يقبل الماضي بحرّية في الفترة التأسيسية)</label>
                <input type="date" value={fields.as_of_date ?? ''} onChange={(e) => setField('as_of_date', e.target.value)} />
              </div>
            </div>
            <div className="op-row">
              <label className="field-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="radio" name="opening-side" checked={fields.is_debit === 'true'} onChange={() => setField('is_debit', 'true')} />مدين
              </label>
              <label className="field-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="radio" name="opening-side" checked={fields.is_debit === 'false'} onChange={() => setField('is_debit', 'false')} />دائن
              </label>
            </div>
            <div className="op-row">
              <div className="field">
                <label className="field-label">مصدر الرصيد</label>
                <select value={fields.source_type ?? ''} onChange={(e) => setField('source_type', e.target.value)}>
                  <option value="" disabled>اختر</option>
                  <option value="VERIFIED">مُتحقَّق منه</option>
                  <option value="RECONSTRUCTED">مُعاد بناؤه</option>
                  <option value="KNOWN_BALANCE">رصيد معروف</option>
                  <option value="ADJUSTMENT">تسوية</option>
                </select>
              </div>
              <div className="field">
                <label className="field-label">درجة الثقة (تُحدِّد الطرف المقابل تلقائياً)</label>
                <select value={fields.confidence ?? ''} onChange={(e) => setField('confidence', e.target.value)}>
                  <option value="" disabled>اختر</option>
                  <option value="HIGH">عالية → 3100 رأس المال</option>
                  <option value="MEDIUM">متوسطة → 3900 فروق تأسيسية</option>
                  <option value="LOW">منخفضة → 3900 فروق تأسيسية</option>
                </select>
              </div>
            </div>
            <div className="field">
              <label className="field-label">ملاحظة (اختياري)</label>
              <input value={fields.source_note ?? ''} onChange={(e) => setField('source_note', e.target.value)} />
            </div>
          </>
        )}

        {tab === 'ADJUSTMENT' && (
          <>
            {/* استثناء مقصود — بلا تصفية عبر for-operation، نفس سبب OPENING أعلاه:
                تسوية قد تمسّ أي حساب في الشجرة، لا الصندوق وحده. */}
            <AccountSelect value={fields.account_code ?? ''} onChange={(v) => setField('account_code', v)} accounts={accounts} label="الحساب" />
            <div className="op-row">
              <div className="field">
                <label className="field-label">العملة</label>
                <CurrencySelect value={fields.currency_code ?? ''} onChange={(v) => setField('currency_code', v)} currencies={currencies} />
              </div>
              <div className="field field-amount">
                <label className="field-label">المبلغ</label>
                <input className="num" value={fields.amount ?? ''} onChange={(e) => setField('amount', e.target.value)} />
              </div>
            </div>
            <div className="op-row">
              <label className="field-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="radio" name="adj-side" checked={fields.is_debit === 'true'} onChange={() => setField('is_debit', 'true')} />
                زيادة في الصندوق (فائض جرد)
              </label>
              <label className="field-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="radio" name="adj-side" checked={fields.is_debit === 'false'} onChange={() => setField('is_debit', 'false')} />
                عجز في الصندوق (نقص جرد)
              </label>
            </div>
            <div className="field">
              <label className="field-label">السبب (إلزامي)</label>
              <input value={fields.reason ?? ''} onChange={(e) => setField('reason', e.target.value)} />
            </div>
          </>
        )}

        {(tab === 'RECEIPT' || tab === 'PAYMENT' || tab === 'EXCHANGE' || tab === 'CASH_TRANSFER') && (
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
        )}

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
            {success.beneficiary_name_snapshot && (
              <div style={{ marginTop: 6 }}>
                أُرسل إلى: {success.beneficiary_name_snapshot} — {success.account_number_snapshot}
                {success.bank_name_snapshot && ` (${success.bank_name_snapshot})`}
                <span className="text-muted"> — لقطة وقت الترحيل، لا تتأثر بتعديل المستفيد لاحقاً</span>
              </div>
            )}
          </div>
        )}

        <div className="op-shortcuts">
          <span className="kbd-chip">Enter حفظ وترحيل</span>
          <span className="kbd-chip">Ctrl+Enter حفظ وطباعة</span>
          <span className="kbd-chip">Esc إلغاء</span>
        </div>

        <button
          type="button" className="btn btn-primary btn-lg" style={{ width: '100%' }}
          disabled={busy || (needsClient && !client) || adminBlocked} onClick={() => submit()}
        >
          حفظ وترحيل
        </button>
      </div>
    </section>
  )
}
