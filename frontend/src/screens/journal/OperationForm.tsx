import { useEffect, useMemo, useState } from 'react'
import {
  ArrowDownUp, Ban, CreditCard, HandCoins, Landmark, MoreHorizontal, PlusCircle, Receipt, Repeat, Scale, Send, Wallet2,
} from 'lucide-react'
import { api, ApiError, newIdempotencyKey } from '../../api/client'
import type {
  ClientBalance, ClientSearchResult, Currency, EditResponse, EntryResponse, Location,
  PendingSwiftMovement,
} from '../../api/types'
import { PIVOT_CODE, convertPreview, profitOrLossLabel, rateDirectionHint, roundCollectedFromClient, roundGivenToClient, roundInternal } from '../../lib/fxPreview'
import { useReferenceData } from '../../hooks/useReferenceData'
import { AccountPicker, type AccountPickerSpec } from '../../components/AccountPicker'
import { DecimalError, DecimalInput } from '../../components/DecimalInput'
import { decimalInputError } from '../../lib/decimalInput'
import { SegmentedTabs } from '../../components/SegmentedTabs'
import { AmountStage, ExchangeSummary, FormGuide, PillTabs, SelectWrap } from './journalUi'
import './journal-design.css'

// ٢٠٢٦-٠٩-٢٢: "اليوم" بتوقيت العمل (Africa/Tripoli) — لا `new Date()` خام
// (قد يختلف يوم العمل عن يوم المتصفح المحلي قرب منتصف الليل). صيغة
// en-CA تُنتج YYYY-MM-DD مباشرة، نفس ما يتوقعه <input type="date">.
function todayInTripoli(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Tripoli' }).format(new Date())
}

// ٢٠٢٦-٠٩-٢٣: "آخر مراسل استُخدم" لحساب تكلفة العمولة (طلب مالك) — تفضيل
// شخصي لهذا الجهاز/المتصفح فقط، لا حالة يشاركها موظفون آخرون ولا يقرؤها
// الخادم، فتخزين محلي بسيط يكفي (يُغلَّف بـtry/catch: قد يُحجَب في تصفح خاص).
const LAST_COST_CORRESPONDENT_KEY = 'wamda:lastCostCorrespondentAccount'
function lastCostCorrespondent(): string {
  try {
    return localStorage.getItem(LAST_COST_CORRESPONDENT_KEY) ?? ''
  } catch {
    return ''
  }
}
function rememberCostCorrespondent(code: string) {
  try {
    localStorage.setItem(LAST_COST_CORRESPONDENT_KEY, code)
  } catch {
    // تجاهل — مجرد تحسين تجربة، لا وظيفة أساسية
  }
}

type OpTab =
  | 'RECEIPT' | 'PAYMENT' | 'EXCHANGE' | 'CASH_TRANSFER' | 'REMIT_OUT' | 'EXPENSE'
  | 'SWIFT_OUT' | 'SWIFT_IN' | 'SWIFT_RETURN' | 'LOCAL_MOVE' | 'OPENING' | 'ADJUSTMENT'

type TabTone = 'in' | 'out' | 'exchange' | 'commission' | 'neutral'
interface TabMeta { id: OpTab; label: string; icon: typeof HandCoins; tone: TabTone }

// ج-٣: ١٢ عملية في مستويين — الأول يغطي أكثر من ٩٠٪ من الحركة اليومية.
// نفس الأيقونة/اللون لكل نوع في NewOperationPanel.tsx — هوية بصرية واحدة
// للعملية بصرف النظر عن أين تظهر في النظام.
const LEVEL1: TabMeta[] = [
  { id: 'RECEIPT', label: 'قبض', icon: HandCoins, tone: 'in' },
  { id: 'PAYMENT', label: 'صرف', icon: Wallet2, tone: 'out' },
  { id: 'EXCHANGE', label: 'صرافة', icon: ArrowDownUp, tone: 'exchange' },
  { id: 'CASH_TRANSFER', label: 'تحويل بعمولة', icon: Repeat, tone: 'neutral' },
  { id: 'REMIT_OUT', label: 'إرسال خارجي', icon: Send, tone: 'commission' },
  { id: 'EXPENSE', label: 'مصروف', icon: Receipt, tone: 'neutral' },
]
const LEVEL2: TabMeta[] = [
  { id: 'SWIFT_OUT', label: 'سويفت خروج', icon: Send, tone: 'neutral' },
  { id: 'SWIFT_IN', label: 'سويفت وصول', icon: Landmark, tone: 'neutral' },
  { id: 'SWIFT_RETURN', label: 'سويفت مرتجع', icon: Ban, tone: 'out' },
  { id: 'LOCAL_MOVE', label: 'نقل داخلي', icon: CreditCard, tone: 'neutral' },
  { id: 'OPENING', label: 'رصيد افتتاحي', icon: PlusCircle, tone: 'neutral' },
  { id: 'ADJUSTMENT', label: 'تسوية', icon: Scale, tone: 'exchange' },
]
const ALL_TABS = [...LEVEL1, ...LEVEL2]

// العمليات التي تمسّ حساب عميل مباشرة — البقية تخصّ الشركة/الشريك وحدها
// أسماء الحقول الرقمية في الحمولة ← الاسم الظاهر في الشاشة (للرسالة العربية)
const NUMERIC_FIELD_LABELS: Record<string, string> = {
  amount: 'المبلغ', total_amount: 'المبلغ', cost_rate: 'سعر التكلفة', client_rate: 'سعر العميل',
  fee_amount: 'الرسوم', return_fee_amount: 'رسوم الإرجاع', bank_conversion_rate: 'سعر تحويل البنك',
  client_commission_amount: 'عمولة العميل', cost_commission_amount: 'تكلفة العمولة',
}

const REQUIRES_CLIENT = new Set<OpTab>(['RECEIPT', 'PAYMENT', 'EXCHANGE', 'CASH_TRANSFER', 'REMIT_OUT', 'SWIFT_RETURN'])
const ADMIN_ONLY_TABS = new Set<OpTab>(['OPENING', 'ADJUSTMENT'])

function CurrencySelect({ value, onChange, currencies }: { value: string; onChange: (v: string) => void; currencies: Currency[] }) {
  return (
    <SelectWrap>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="" disabled>العملة</option>
        {currencies.map((c) => <option key={c.code} value={c.code}>{c.name_ar}</option>)}
      </select>
    </SelectWrap>
  )
}

function LocationSelect({ value, onChange, locations, disabled }: { value: string; onChange: (v: string) => void; locations: Location[]; disabled?: boolean }) {
  return (
    <SelectWrap>
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
        <option value="" disabled>الموقع</option>
        {locations.map((l) => <option key={l.code} value={l.code}>{l.name_ar}</option>)}
      </select>
    </SelectWrap>
  )
}

interface OperationFormProps {
  client: ClientSearchResult | null
  currentUserRole: 'ADMIN' | 'ACCOUNTANT'
  onPosted: (entry: EntryResponse) => void
  onOpenWizard: () => void
  requestedTab?: string | null
  // أ: وضع التعديل — نفس النموذج حرفياً، نوع العملية مثبَّت (لا تبويبات ولا
  // معالج خطوتين)، حقل سبب إضافي، والإرسال يذهب لـ/operations/{id}/edit
  // بدل مسار الإنشاء. مكوّن واحد مشترك بين الإنشاء والتعديل — لا نسخة ثانية.
  mode?: 'create' | 'edit'
  editEntryId?: number
  onEdited?: (result: EditResponse) => void
  onCancelEdit?: () => void
}

export function OperationForm({
  client, currentUserRole, onPosted, onOpenWizard, requestedTab,
  mode = 'create', editEntryId, onEdited, onCancelEdit,
}: OperationFormProps) {
  const { currencies, locationsForCurrency } = useReferenceData()
  const [tab, setTab] = useState<OpTab>('RECEIPT')
  const [moreOpen, setMoreOpen] = useState(false)
  const [idemKey, setIdemKey] = useState(newIdempotencyKey())
  const [editReason, setEditReason] = useState('')
  const [busy, setBusy] = useState(false)
  // الخطأ مرتبط بقيم النموذج لحظة الإرسال (`formKey`)؛ أيّ تعديل لاحق لأي
  // حقل يُخفيه — ٢٠٢٦-١٠-٠٢: كان رد ٤٢٢ لمحاولة سابقة (cost_rate=0) يبقى ظاهراً
  // بجوار حقل صُحِّح إلى ٩٫٠٥ فيبدو كأن الخادم استلم ٠ من القيمة المعروضة.
  const [errorState, setErrorState] = useState<{ message: string; atKey: string } | null>(null)
  const [success, setSuccess] = useState<EntryResponse | null>(null)
  // ب: رصيد صندوق/مراسل سيصبح سالباً — الخادم يرفض بـ٤٠٩ فور المحاولة
  // العادية؛ هذا يحفظ نفس الطلب لإعادة إرساله بعد إدخال سبب إلزامي
  // (allow_negative+override_reason)، بدل رفض تام بلا أي وسيلة تجاوز.
  const [negOverride, setNegOverride] = useState<{ url: string; retryPayload: (reason: string) => Record<string, unknown> } | null>(null)
  const [negReason, setNegReason] = useState('')
  // ج: تاريخ العملية (طلب مالك ٢٠٢٦-٠٩-٢٢) — مشترك لكل التبويبات ما عدا
  // OPENING (له `as_of_date` خاص بنفس الدور أصلاً). نفس نمط negOverride
  // أعلاه لإعادة الإرسال بسبب بعد رفض ٤٢٢ "بأثر رجعي بعد الإقفال".
  const [entryDate, setEntryDate] = useState(() => todayInTripoli())
  const [backdateReason, setBackdateReason] = useState('')
  const [backdateOverride, setBackdateOverride] = useState<{ url: string; retryPayload: (reason: string) => Record<string, unknown> } | null>(null)
  const [backdateOverrideReason, setBackdateOverrideReason] = useState('')

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
  // ٢٠٢٦-٠٩-٢٤ (طلب مالك — لا نوع عملية ثالث عشر): EXCHANGE نفسه بمنطقه
  // القائم، فقط بنطاق مختلف — CLIENT (الأصل) أو TREASURY (بين حسابي
  // شركة عبر مراسل طرف ثالث، لا عميل في القيد إطلاقاً). "سعر العميل"
  // يصبح مفهومياً "سعر التنفيذ" في نطاق الخزينة، لكن نفس الحقل/الحالة.
  const [exchangeScope, setExchangeScope] = useState<'CLIENT' | 'TREASURY'>('CLIENT')
  const [treasurySourceAccount, setTreasurySourceAccount] = useState('')
  const [treasuryDestAccount, setTreasuryDestAccount] = useState('')
  const [treasurySourceName, setTreasurySourceName] = useState('')
  const [treasuryDestName, setTreasuryDestName] = useState('')
  const [fromLocation, setFromLocation] = useState('')
  const [toLocationCt, setToLocationCt] = useState('')
  const [sourceAccount, setSourceAccount] = useState('')
  const [executionAccount, setExecutionAccount] = useState('')
  const [collectionAccount, setCollectionAccount] = useState('')
  // ٢٠٢٦-٠٩-٢٣: التحصيل من رصيد العميل نفسه هو الافتراضي (توضيح مالك،
  // "الأكثر شيوعاً عندي") — لا حساب شركة يُختار إلا إذا بدَّل المستخدم صراحة.
  const [collectFromCompanyAccount, setCollectFromCompanyAccount] = useState(false)
  const [collectionLocation, setCollectionLocation] = useState('')
  const [commissionCurrency, setCommissionCurrency] = useState('')
  const [clientCommission, setClientCommission] = useState('')
  const [costCommission, setCostCommission] = useState('')
  const [costCorrespondentAccount, setCostCorrespondentAccount] = useState(() => lastCostCorrespondent())

  // حقول الثماني عمليات الجديدة (المرحلة ٧) — كائن عام واحد، أبسط من
  // إضافة ٣٠+ useState فردياً لكل حقل من كل عملية
  const [fields, setFields] = useState<Record<string, string>>({})
  const setField = (key: string, value: string) => setFields((f) => ({ ...f, [key]: value }))

  const [pendingSwift, setPendingSwift] = useState<PendingSwiftMovement[]>([])
  const [openingAccountMode, setOpeningAccountMode] = useState<'system' | 'client'>('system')
  const [clientBalancesForOpening, setClientBalancesForOpening] = useState<ClientBalance[]>([])

  const formKey = JSON.stringify([
    tab, exchangeScope, currencyCode, locationCode, amount, accountCode, toCurrency, toLocation, costRate, clientRate,
    negativeMarginReason, treasurySourceAccount, treasuryDestAccount, fromLocation, toLocationCt, sourceAccount,
    executionAccount, collectionAccount, collectFromCompanyAccount, collectionLocation, commissionCurrency,
    clientCommission, costCommission, costCorrespondentAccount, fields, entryDate, backdateReason, editReason,
    client?.id ?? null, openingAccountMode,
  ])
  const error = errorState && errorState.atKey === formKey ? errorState.message : null
  const setError = (message: string | null) => setErrorState(message === null ? null : { message, atKey: formKey })

  function resetForm() {
    setCurrencyCode(''); setLocationCode(''); setAmount(''); setAccountCode('')
    setToCurrency(''); setToLocation(''); setCostRate(''); setClientRate(''); setNegativeMarginReason('')
    setFromLocation(''); setToLocationCt(''); setCommissionCurrency('')
    setClientCommission(''); setCostCommission(''); setSourceAccount(''); setExecutionAccount('')
    setCollectionAccount(''); setCollectFromCompanyAccount(false); setCollectionLocation('')
    setCostCorrespondentAccount(lastCostCorrespondent())
    setExchangeScope('CLIENT'); setTreasurySourceAccount(''); setTreasuryDestAccount('')
    setTreasurySourceName(''); setTreasuryDestName('')
    setFields({})
    setOpeningAccountMode('system')
    setIdemKey(newIdempotencyKey())
    setSuccess(null)
    setNegOverride(null)
    setNegReason('')
    setEntryDate(todayInTripoli())
    setBackdateReason('')
    setBackdateOverride(null)
    setBackdateOverrideReason('')
  }

  useEffect(() => { resetForm() }, [tab])

  useEffect(() => {
    if (requestedTab && ALL_TABS.some((t) => t.id === requestedTab)) {
      setTab(requestedTab as OpTab)
      if (LEVEL2.some((t) => t.id === requestedTab)) setMoreOpen(true)
    }
  }, [requestedTab])


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
  const ctCollectionLocations = useMemo(() => locationsForCurrency(commissionCurrency), [commissionCurrency, locationsForCurrency])
  const remitLocations = useMemo(() => locationsForCurrency(PIVOT_CODE), [locationsForCurrency])

  // حسابات مُصفّاة بحسب (نوع العملية × دور الحقل × العملة × الموقع) —
  // AccountPicker يجلبها بنفسه (حياً، عند كل فتح) عبر /reference/accounts/for-operation.
  // spec=null يعني "هذا الحقل غير معني بالتبويب الحالي" فلا يُطلَق أي جلب.
  const receivingPayingSpec: AccountPickerSpec | null =
    tab === 'RECEIPT' || tab === 'PAYMENT'
      ? { mode: 'operation', operationType: tab, field: tab === 'RECEIPT' ? 'receiving' : 'paying', currencyCode, locationCode: locationCode || undefined }
      : null

  // EXCHANGE نطاق الخزينة (٢٠٢٦-٠٩-٢٤) — بلا قيد موقع، أي حساب شركة
  // بعملة كل طرف (المصدر بعملة "من"، الوجهة بعملة "إلى").
  const exchangeSourceSpec: AccountPickerSpec | null =
    tab === 'EXCHANGE' && exchangeScope === 'TREASURY' ? { mode: 'operation', operationType: 'EXCHANGE', field: 'source', currencyCode } : null
  const exchangeDestSpec: AccountPickerSpec | null =
    tab === 'EXCHANGE' && exchangeScope === 'TREASURY' ? { mode: 'operation', operationType: 'EXCHANGE', field: 'destination', currencyCode: toCurrency } : null

  const ctSourceSpec: AccountPickerSpec | null =
    tab === 'CASH_TRANSFER' ? { mode: 'operation', operationType: 'CASH_TRANSFER', field: 'source', currencyCode, locationCode: fromLocation || undefined } : null

  const ctExecutionSpec: AccountPickerSpec | null =
    tab === 'CASH_TRANSFER' ? { mode: 'operation', operationType: 'CASH_TRANSFER', field: 'execution', currencyCode, locationCode: toLocationCt || undefined } : null

  // ٢٠٢٦-٠٩-٢٣ (توضيح مالك): عملة/حساب العمولة مستقلّان تماماً عن موقع
  // الوجهة — كانا مربوطين بـtoLocationCt خطأً (عمولة دينار لتحويل هدفه
  // تركيا لا علاقة لها بتركيا إطلاقاً). كلا الحقلين الآن بلا قيد موقع.
  const ctCollectionSpec: AccountPickerSpec | null =
    tab === 'CASH_TRANSFER' && collectFromCompanyAccount ? { mode: 'operation', operationType: 'CASH_TRANSFER', field: 'collection', currencyCode: commissionCurrency } : null

  const ctCostCorrespondentSpec: AccountPickerSpec | null =
    tab === 'CASH_TRANSFER' ? { mode: 'operation', operationType: 'CASH_TRANSFER', field: 'cost_correspondent', currencyCode: commissionCurrency } : null

  const localMoveFromSpec: AccountPickerSpec | null =
    tab === 'LOCAL_MOVE' ? { mode: 'operation', operationType: 'LOCAL_MOVE', field: 'from', currencyCode: fields.currency_code ?? '' } : null

  const localMoveToSpec: AccountPickerSpec | null =
    tab === 'LOCAL_MOVE' ? { mode: 'operation', operationType: 'LOCAL_MOVE', field: 'to', currencyCode: fields.currency_code ?? '' } : null

  const swiftOutPartnerSpec: AccountPickerSpec | null =
    tab === 'SWIFT_OUT' ? { mode: 'operation', operationType: 'SWIFT_OUT', field: 'partner', currencyCode: PIVOT_CODE } : null

  // عملة الاستقبال تتبع وجود سعر تحويل البنك: بلا سعر = إيداع دولار مباشر،
  // بسعر = فتح دفعة رمبي (انظر الشارة الديناميكية أدناه) — نفس المنطق هنا.
  const swiftInCurrency = fields.bank_conversion_rate ? 'CNY' : PIVOT_CODE
  const swiftInReceivingSpec: AccountPickerSpec | null =
    tab === 'SWIFT_IN' ? { mode: 'operation', operationType: 'SWIFT_IN', field: 'receiving', currencyCode: swiftInCurrency } : null

  const remitOutPartnerSpec: AccountPickerSpec | null =
    tab === 'REMIT_OUT' ? { mode: 'operation', operationType: 'REMIT_OUT', field: 'partner', currencyCode: PIVOT_CODE, locationCode: fields.from_location_code || undefined } : null

  const expensePayingSpec: AccountPickerSpec | null =
    tab === 'EXPENSE' ? { mode: 'operation', operationType: 'EXPENSE', field: 'paying', currencyCode: fields.currency_code ?? '' } : null

  const fullAccountListSpec: AccountPickerSpec | null = (tab === 'OPENING' && openingAccountMode === 'system') || tab === 'ADJUSTMENT'
    ? { mode: 'full' }
    : null

  // بند المصروف (EXPENSE) — لا مواصفة تصفية خادمية له في account_filters.py
  // (النوع لا الدور محدِّد الحقل هنا)، فيُجلب الكل ويُصفَّى جانب العميل.
  const expenseCategorySpec: AccountPickerSpec | null = tab === 'EXPENSE' ? { mode: 'full' } : null

  const selectedReturnMovement = pendingSwift.find((m) => m.id === Number(fields.swift_movement_id))

  // معاينة فورية — decimal.js في المتصفح فقط، السيرفر يعيد الحساب ويحسم
  const exchangePreview = useMemo(() => {
    if (tab !== 'EXCHANGE' || exchangeScope !== 'CLIENT' || !currencyCode || !toCurrency || !amount) return null
    const toCcy = currencies.find((c) => c.code === toCurrency)
    if (!toCcy) return null
    const clientAmt = roundGivenToClient(convertPreview(amount, clientRate, currencyCode), toCcy.decimals)
    const costAmt = roundInternal(convertPreview(amount, costRate, currencyCode), toCcy.decimals)
    return { clientAmt, costAmt, diff: costAmt.minus(clientAmt) }
  }, [tab, exchangeScope, currencyCode, toCurrency, amount, clientRate, costRate, currencies])

  // نطاق الخزينة (٢٠٢٦-١٠-٠٢): سعر واحد منفَّذ، لا تكلفة ولا ربح — المبلغ
  // الداخل = المبلغ الخارج × السعر (نفس تقريب الخادم: للأسفل).
  const treasuryPreview = useMemo(() => {
    if (tab !== 'EXCHANGE' || exchangeScope !== 'TREASURY' || !currencyCode || !toCurrency || !amount || !clientRate) return null
    const toCcy = currencies.find((c) => c.code === toCurrency)
    if (!toCcy) return null
    return { toAmount: roundGivenToClient(convertPreview(amount, clientRate, currencyCode), toCcy.decimals) }
  }, [tab, exchangeScope, currencyCode, toCurrency, amount, clientRate, currencies])

  // §٤ رقم ٩: موجب = ربح (العميل دفع أكثر من التكلفة) — عكس إشارة الصرافة تماماً
  const remitPreview = useMemo(() => {
    if (tab !== 'REMIT_OUT' || !fields.currency_code || !fields.amount) return null
    const usd = currencies.find((c) => c.code === PIVOT_CODE)
    if (!usd) return null
    const clientRaw = convertPreview(fields.amount, fields.client_rate ?? '', fields.currency_code)
    const costRaw = convertPreview(fields.amount, fields.cost_rate ?? '', fields.currency_code)
    const clientAmt = roundCollectedFromClient(clientRaw, usd.decimals)
    const costAmt = roundInternal(costRaw, usd.decimals)
    return { clientAmt, costAmt, diff: clientAmt.minus(costAmt) }
  }, [tab, fields.currency_code, fields.amount, fields.client_rate, fields.cost_rate, currencies])

  // ب: يبني {url, payload} فقط — لا يرسل — كي يُعاد استخدام نفس الجسم عند
  // إعادة المحاولة بعد تجاوز رصيد سالب (allow_negative+override_reason
  // يُضافان لاحقاً بلا تكرار كل هذا التفريع من جديد).
  function buildRequest(): { url: string; payload: Record<string, unknown> } | null {
    if (tab === 'RECEIPT') {
      return { url: '/operations/receipt', payload: {
        client_id: client!.id, currency_code: currencyCode, location_code: locationCode,
        amount, receiving_account_code: accountCode, note: fields.note || undefined,
      } }
    } else if (tab === 'PAYMENT') {
      return { url: '/operations/payment', payload: {
        client_id: client!.id, currency_code: currencyCode, location_code: locationCode,
        amount, paying_account_code: accountCode, note: fields.note || undefined,
      } }
    } else if (tab === 'EXCHANGE') {
      return { url: '/operations/exchange', payload: exchangeScope === 'TREASURY' ? {
        source_account_code: treasurySourceAccount, destination_account_code: treasuryDestAccount,
        from_currency: currencyCode, to_currency: toCurrency, amount,
        client_rate: clientRate, note: fields.note || undefined,
      } : {
        client_id: client!.id, from_currency: currencyCode, from_location_code: locationCode,
        to_currency: toCurrency, to_location_code: toLocation, amount, cost_rate: costRate,
        client_rate: clientRate, negative_margin_reason: negativeMarginReason || undefined, note: fields.note || undefined,
      } }
    } else if (tab === 'CASH_TRANSFER') {
      return { url: '/operations/cash-transfer', payload: {
        client_id: client!.id, currency_code: currencyCode, from_location_code: fromLocation,
        to_location_code: toLocationCt, amount, source_account_code: sourceAccount,
        execution_account_code: executionAccount,
        // لا حساب شركة إلا إذا بدَّل المستخدم صراحة — غير ذلك يُخصَم من
        // رصيد العميل (افتراضي الخادم)، بموقع collectionLocation إن اختير.
        collection_account_code: collectFromCompanyAccount ? collectionAccount : undefined,
        collection_location_code: collectFromCompanyAccount ? undefined : (collectionLocation || undefined),
        commission_currency: commissionCurrency, client_commission_amount: clientCommission,
        cost_commission_amount: costCommission, cost_correspondent_account_code: costCorrespondentAccount, note: fields.note || undefined,
      } }
    } else if (tab === 'REMIT_OUT') {
      return { url: '/operations/remit-out', payload: {
        client_id: client!.id, from_location_code: fields.from_location_code,
        partner_account_code: fields.partner_account_code, currency_code: fields.currency_code,
        amount: fields.amount, cost_rate: fields.cost_rate, client_rate: fields.client_rate,
        negative_margin_reason: fields.negative_margin_reason || undefined, note: fields.note || undefined,
      } }
    } else if (tab === 'EXPENSE') {
      return { url: '/operations/expense', payload: {
        expense_account_code: fields.expense_account_code, currency_code: fields.currency_code,
        paying_account_code: fields.paying_account_code, amount: fields.amount, description: fields.description, note: fields.note || undefined,
      } }
    } else if (tab === 'SWIFT_OUT') {
      return { url: '/operations/swift-out', payload: {
        partner_account_code: fields.partner_account_code, amount: fields.amount,
        external_ref: fields.external_ref || undefined, description: fields.description || undefined, note: fields.note || undefined,
      } }
    } else if (tab === 'SWIFT_IN') {
      return { url: '/operations/swift-in', payload: {
        swift_movement_id: Number(fields.swift_movement_id), total_amount: fields.total_amount,
        fee_amount: fields.fee_amount || '0', receiving_account_code: fields.receiving_account_code,
        bank_conversion_rate: fields.bank_conversion_rate || undefined, note: fields.note || undefined,
      } }
    } else if (tab === 'SWIFT_RETURN') {
      // partner_account_code مُشتقّ من الحركة نفسها — لا اختيار يدوي (انظر التعليق في JSX)
      return { url: '/operations/swift-return', payload: {
        swift_movement_id: Number(fields.swift_movement_id), partner_account_code: selectedReturnMovement?.partner_account_code,
        total_amount: fields.total_amount, client_id: client!.id, client_location_code: fields.client_location_code,
        return_fee_amount: fields.return_fee_amount || '0', note: fields.note || undefined,
      } }
    } else if (tab === 'LOCAL_MOVE') {
      return { url: '/operations/local-move', payload: {
        currency_code: fields.currency_code, from_account_code: fields.from_account_code,
        to_account_code: fields.to_account_code, amount: fields.amount, fee_amount: fields.fee_amount || '0', note: fields.note || undefined,
      } }
    } else if (tab === 'OPENING') {
      return { url: '/operations/opening', payload: {
        account_code: fields.account_code, currency_code: fields.currency_code, amount: fields.amount,
        is_debit: fields.is_debit === 'true', as_of_date: fields.as_of_date, source_type: fields.source_type,
        confidence: fields.confidence, source_note: fields.source_note || undefined, note: fields.note || undefined,
      } }
    }
    // ADJUSTMENT: السبب إلزامي أصلاً في الحقل أدناه ويُعاد استخدامه داخل
    // المحرك نفسه كـoverride_reason (app/engine/operations/adjustment.py) —
    // allow_negative صريحة هنا مباشرة، بلا حاجة لجولة تجاوز إضافية لأن
    // الإقرار موجود سلفاً قبل الإرسال.
    return { url: '/operations/adjustment', payload: {
      account_code: fields.account_code, currency_code: fields.currency_code, amount: fields.amount,
      is_debit: fields.is_debit === 'true', reason: fields.reason, note: fields.note || undefined,
      allow_negative: true,
    } }
  }

  // mode='edit': يُرسِل إلى /operations/{id}/edit بجسم {reason, operation}
  // بدل مسار الإنشاء المباشر — retryPayload يبني جسم إعادة المحاولة الصحيح
  // لكلا الوضعين (تعديل يحتاج تغليف operation من جديد، إنشاء لا).
  async function doSubmit(
    url: string, payload: Record<string, unknown>, printAfter: boolean,
    retryNegative: (reason: string) => Record<string, unknown>,
    retryBackdate: (reason: string) => Record<string, unknown>,
  ) {
    setBusy(true)
    setError(null)
    try {
      if (mode === 'edit') {
        const result = await api.post<EditResponse>(url, payload)
        onEdited?.(result)
      } else {
        const entry = await api.post<EntryResponse>(url, payload, idemKey)
        if (tab === 'CASH_TRANSFER' && costCorrespondentAccount) rememberCostCorrespondent(costCorrespondentAccount)
        resetForm()
        setSuccess(entry)
        onPosted(entry)
        if (printAfter) window.print()
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.message.includes('سيصبح سالباً')) {
        setNegOverride({ url, retryPayload: retryNegative })
        setNegReason('')
      } else if (err instanceof ApiError && err.status === 422 && err.message.includes('بأثر رجعي')) {
        setBackdateOverride({ url, retryPayload: retryBackdate })
        setBackdateOverrideReason('')
      } else {
        setError(err instanceof ApiError ? err.message : (mode === 'edit' ? 'تعذّر التعديل' : 'تعذّر الترحيل'))
      }
    } finally {
      setBusy(false)
    }
  }

  async function submit(printAfter = false) {
    const needsClient = REQUIRES_CLIENT.has(tab) && !(tab === 'EXCHANGE' && exchangeScope === 'TREASURY')
    if (needsClient && !client) {
      setError('اختر عميلاً أولاً')
      return
    }
    const req = buildRequest()
    if (!req) return
    // قيمة رقمية غير صالحة (فاصلة «,» مثلاً) لا تُرسَل — رسالة عربية باسم الحقل
    for (const [key, label] of Object.entries(NUMERIC_FIELD_LABELS)) {
      const raw = req.payload[key]
      const message = typeof raw === 'string' ? decimalInputError(raw) : null
      if (message) {
        const shown = key === 'client_rate' && exchangeScope === 'TREASURY' && tab === 'EXCHANGE' ? 'سعر التنفيذ' : label
        setError(`«${shown}»: ${message}`)
        return
      }
    }
    // ج: OPENING له as_of_date الخاص به أصلاً (نفس الدور) — لا يُضاف تاريخ
    // مشترك ثانٍ فوقه. كل التبويبات الأخرى تحمل entry_date/backdate_reason.
    const payload = tab === 'OPENING'
      ? req.payload
      : { ...req.payload, entry_date: entryDate || undefined, backdate_reason: backdateReason.trim() || undefined }
    if (mode === 'edit') {
      if (!editReason.trim()) {
        setError('سبب التعديل إلزامي')
        return
      }
      const url = `/operations/${editEntryId}/edit`
      const body = { reason: editReason.trim(), operation: payload }
      await doSubmit(
        url, body, false,
        (reason) => ({ reason: editReason.trim(), operation: { ...payload, allow_negative: true, override_reason: reason } }),
        (reason) => ({ reason: editReason.trim(), operation: { ...payload, backdate_reason: reason } }),
      )
      return
    }
    await doSubmit(
      req.url, payload, printAfter,
      (reason) => ({ ...payload, allow_negative: true, override_reason: reason }),
      (reason) => ({ ...payload, backdate_reason: reason }),
    )
  }

  // ب: تأكيد صريح بعد إدخال سبب — الطلب نفسه يُعاد بـallow_negative+
  // override_reason مُضافين؛ الخادم يفرض ADMIN فقط بصرف النظر عن هذا
  // (Action.OVERRIDE_CREDIT_OR_BALANCE)، فلا حاجة لفحص دور إضافي هنا.
  async function confirmNegativeOverride() {
    if (!negOverride || !negReason.trim()) return
    const { url, retryPayload } = negOverride
    const body = retryPayload(negReason.trim())
    setNegOverride(null)
    await doSubmit(url, body, false, retryPayload, retryPayload)
  }

  // نفس نمط confirmNegativeOverride أعلاه — الفترة الشهرية مقفلة والمستخدم
  // مدير فعلاً (وإلا كان الرفض ٤٠٣ لا ٤٢٢ ولا يصل لهذا المسار إطلاقاً)،
  // ينقصه فقط سبب القيد بأثر رجعي.
  async function confirmBackdateOverride() {
    if (!backdateOverride || !backdateOverrideReason.trim()) return
    const { url, retryPayload } = backdateOverride
    const body = retryPayload(backdateOverrideReason.trim())
    setBackdateOverride(null)
    await doSubmit(url, body, false, retryPayload, retryPayload)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape') {
      e.preventDefault()
      if (mode === 'edit') onCancelEdit?.()
      else resetForm()
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (!busy) void submit(e.ctrlKey)
    }
  }

  const needsClient = REQUIRES_CLIENT.has(tab) && !(tab === 'EXCHANGE' && exchangeScope === 'TREASURY')
  const adminBlocked = ADMIN_ONLY_TABS.has(tab) && currentUserRole !== 'ADMIN'
  const isEdit = mode === 'edit'
  const activeMeta = ALL_TABS.find((t) => t.id === tab)

  function toDockItems(metas: TabMeta[]) {
    return metas.map((t) => ({ id: t.id, label: t.label, tone: t.tone, icon: <t.icon size={15} strokeWidth={2} /> }))
  }

  return (
    <section className="journal-col journal-col-center">
      {!isEdit && (
        <div className="operation-dock">
          <SegmentedTabs
            variant="dock" ariaLabel="نوع العملية" value={tab}
            onChange={(id) => { setTab(id); setMoreOpen(false) }}
            items={toDockItems(LEVEL1)}
          />
          <button
            type="button" className={`operation-tab more-tab${moreOpen ? ' is-active' : ''}`}
            aria-expanded={moreOpen} onClick={() => setMoreOpen((v) => !v)}
          >
            <MoreHorizontal size={16} strokeWidth={2} />
            <span>المزيد</span>
          </button>
        </div>
      )}

      {!isEdit && moreOpen && (
        <div className="operation-dock">
          <SegmentedTabs variant="dock" ariaLabel="أنواع إضافية" value={tab} onChange={setTab} items={toDockItems(LEVEL2)} />
        </div>
      )}

      {!isEdit && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 4 }}>
          <button type="button" className="btn-text" onClick={onOpenWizard}>
            معالج الخطوتين (دينار → دولار → رمبي)
          </button>
        </div>
      )}

      <div className="composer-panel" onKeyDown={handleKeyDown}>
        <div className="composer-head">
          <div>
            <h2>{isEdit ? `تعديل — ${activeMeta?.label ?? tab}` : (activeMeta?.label ?? tab)}</h2>
            <p>أدخل بيانات العملية — الحسابات المتاحة تُصفَّى تلقائياً حسب العملة والموقع.</p>
          </div>
        </div>

        {isEdit && <FormGuide tone="warning">تعديل يعكس العملية الأصلية وينشئ بديلاً بالقيم الجديدة — أدخل القيم الكاملة للعملية.</FormGuide>}
        {isEdit && client && (
          <p className="text-muted" style={{ fontSize: 13 }}>العميل: {client.name_ar} ({client.code})</p>
        )}
        {needsClient && !client && <FormGuide tone="info">اختر عميلاً من العمود الأيمن أولاً</FormGuide>}
        {adminBlocked && <FormGuide tone="warning">هذه العملية تتطلب صلاحية مدير — لن يقبلها الخادم لدورك الحالي.</FormGuide>}

        <form className="entry-form" onSubmit={(e) => e.preventDefault()}>
          {/* ج: تاريخ العملية — مشترك لكل التبويبات، ما عدا OPENING (حقله
              الخاص "التاريخ" أدناه بنفس الدور) ووضع التعديل (خارج نطاق هذا
              التعديل). الافتراضي اليوم بتوقيت العمل؛ يقبل أي تاريخ ماضٍ
              بحرّية ما دامت الفترة التأسيسية مفتوحة — بعد إقفال فترة شهرية
              الضوابط القائمة في الخادم تُطبَّق (مدير + سبب إلزامي، ٤٢٢/٤٠٣). */}
          {!isEdit && tab !== 'OPENING' && (
            <div className="date-row">
              <div className="field">
                <label className="field-label" htmlFor="op-entry-date">تاريخ العملية</label>
                <input id="op-entry-date" type="date" max={todayInTripoli()} value={entryDate} onChange={(e) => setEntryDate(e.target.value)} />
              </div>
              {entryDate && entryDate !== todayInTripoli() && (
                <div className="field" style={{ flex: 2 }}>
                  <label className="field-label" htmlFor="op-backdate-reason">سبب القيد بأثر رجعي (إن كانت الفترة مقفلة)</label>
                  <input id="op-backdate-reason" value={backdateReason} onChange={(e) => setBackdateReason(e.target.value)} placeholder="اختياري — يُطلَب فقط إن رفضه الخادم" />
                </div>
              )}
            </div>
          )}
          {!isEdit && tab !== 'OPENING' && (
            entryDate === todayInTripoli() ? (
              <p className="text-muted" style={{ fontSize: 12, margin: '-6px 0 0' }}>سيُسجَّل بتاريخ اليوم ({entryDate})</p>
            ) : (
              <FormGuide tone="warning">⚠ سيُسجَّل بتاريخ ماضٍ: {entryDate} — تحقَّق قبل الحفظ</FormGuide>
            )
          )}

          {tab === 'EXCHANGE' && (
            <PillTabs
              label="نطاق الصرافة"
              value={exchangeScope}
              onChange={setExchangeScope}
              options={[
                { id: 'CLIENT', label: 'عميل' },
                { id: 'TREASURY', label: 'خزينة', title: 'خزينة — بين حسابي شركة' },
              ]}
            />
          )}

          {tab !== 'CASH_TRANSFER' && (tab === 'RECEIPT' || tab === 'PAYMENT' || tab === 'EXCHANGE') && (
            <div className="form-row">
              <div className="field">
                <label className="field-label">العملة</label>
                <CurrencySelect value={currencyCode} onChange={(v) => { setCurrencyCode(v); setLocationCode('') }} currencies={currencies} />
              </div>
              {!(tab === 'EXCHANGE' && exchangeScope === 'TREASURY') && (
                <div className="field">
                  <label className="field-label">الموقع</label>
                  <LocationSelect value={locationCode} onChange={setLocationCode} locations={fromLocations} disabled={!currencyCode} />
                </div>
              )}
            </div>
          )}

          {tab === 'EXCHANGE' && exchangeScope === 'TREASURY' && (
            <AccountPicker
              value={treasurySourceAccount} onChange={(code, a) => { setTreasurySourceAccount(code); setTreasurySourceName(a?.name_ar ?? '') }} spec={exchangeSourceSpec} label="الحساب المصدر"
              emptyMessage={!currencyCode ? 'اختر العملة أولاً' : 'لا حسابات شركة بهذه العملة'}
            />
          )}

          {tab === 'EXCHANGE' && (
            <div className="form-row">
              <div className="field">
                <label className="field-label">إلى عملة</label>
                <CurrencySelect
                  value={toCurrency}
                  onChange={(v) => { setToCurrency(v); setToLocation('') }}
                  currencies={currencies.filter((c) => c.code === PIVOT_CODE || currencyCode === PIVOT_CODE)}
                />
              </div>
              {exchangeScope !== 'TREASURY' && (
                <div className="field">
                  <label className="field-label">إلى موقع</label>
                  <LocationSelect value={toLocation} onChange={setToLocation} locations={toLocations} disabled={!toCurrency} />
                </div>
              )}
            </div>
          )}

          {tab === 'EXCHANGE' && exchangeScope === 'TREASURY' && (
            <AccountPicker
              value={treasuryDestAccount} onChange={(code, a) => { setTreasuryDestAccount(code); setTreasuryDestName(a?.name_ar ?? '') }} spec={exchangeDestSpec} label="الحساب الوجهة"
              emptyMessage={!toCurrency ? 'اختر إلى عملة أولاً' : 'لا حسابات شركة بهذه العملة'}
            />
          )}

          {(tab === 'RECEIPT' || tab === 'PAYMENT') && (
            <AccountPicker
              value={accountCode} onChange={setAccountCode} spec={receivingPayingSpec}
              label={tab === 'RECEIPT' ? 'الحساب المستقبِل' : 'الحساب المصروف منه'}
              emptyMessage={!currencyCode || !locationCode ? 'اختر العملة والموقع أولاً' : 'لا حسابات صناديق/مراسلين/بنوك بهذه العملة والموقع'}
            />
          )}

          {tab === 'CASH_TRANSFER' && (
            <>
              <div className="form-row">
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
              {/* ٢٠٢٦-٠٩-٢٢: حقل المبلغ المنقول كان غائباً كلياً هنا — buildRequest()
                  كان يرسل `amount` الحالة المشتركة (فارغة دائماً بعد resetForm()
                  عند تبديل التبويب) بلا أي وسيلة لملئها؛ أي CASH_TRANSFER حقيقي
                  كان سيُرفَض بمبلغ فارغ. اكتُشف أثناء اختبار حي كامل للإصلاح أعلاه. */}
              <AmountStage id="ct-amount" label={`المبلغ المنقول (${currencyCode || '—'})`} value={amount} onChange={setAmount} currencyCode={currencyCode || undefined} />
              <AccountPicker
                value={sourceAccount} onChange={setSourceAccount} spec={ctSourceSpec} label="حساب المصدر (الشركة)"
                emptyMessage={!currencyCode || !fromLocation ? 'اختر العملة وموقع المصدر أولاً' : 'لا حسابات بهذه العملة في موقع المصدر'}
              />
              <AccountPicker
                value={executionAccount} onChange={setExecutionAccount} spec={ctExecutionSpec} label="الحساب المنفِّذ"
                emptyMessage={!currencyCode || !toLocationCt ? 'اختر العملة وموقع الوجهة أولاً' : 'لا حسابات بهذه العملة في موقع الوجهة'}
              />
              {/* ٢٠٢٦-٠٩-٢٣ (توضيح مالك): عملة/حساب العمولة مستقلّان تماماً عن
                  موقع الوجهة — عمولة دينار تُحصَّل وتُسوَّى في ليبيا لتحويل
                  هدفه تركيا مثلاً. عملة العمولة أولاً هنا كي تُبنى قوائم
                  الحسابات أدناه عليها مباشرة، لا بعد فوات الأوان. */}
              <div className="form-row">
                <div className="field">
                  <label className="field-label">عملة العمولة</label>
                  <CurrencySelect
                    value={commissionCurrency}
                    onChange={(v) => {
                      setCommissionCurrency(v)
                      const valid = locationsForCurrency(v).some((l) => l.code === fromLocation)
                      setCollectionLocation(valid ? fromLocation : '')
                    }}
                    currencies={currencies}
                  />
                </div>
                <div className="field">
                  <label className="field-label">عمولة العميل (تحصيل)</label>
                  <DecimalInput className="num" value={clientCommission} onChange={setClientCommission} />
<DecimalError value={clientCommission} />
                </div>
                <div className="field">
                  <label className="field-label">تكلفة العمولة</label>
                  <DecimalInput className="num" value={costCommission} onChange={setCostCommission} />
<DecimalError value={costCommission} />
                </div>
              </div>

              <div className="field">
                <label className="field-label">حساب تحصيل العمولة</label>
                <PillTabs
                  label="حساب تحصيل العمولة"
                  value={collectFromCompanyAccount ? 'COMPANY' : 'CLIENT'}
                  onChange={(v) => setCollectFromCompanyAccount(v === 'COMPANY')}
                  options={[{ id: 'CLIENT', label: 'من رصيد العميل' }, { id: 'COMPANY', label: 'حساب شركة' }]}
                />
              </div>
              {collectFromCompanyAccount ? (
                <AccountPicker
                  value={collectionAccount} onChange={setCollectionAccount} spec={ctCollectionSpec} label="الحساب"
                  emptyMessage={!commissionCurrency ? 'اختر عملة العمولة أولاً' : 'لا حسابات بعملة العمولة'}
                />
              ) : (
                <div className="field">
                  <label className="field-label">موقع رصيد العميل المخصوم منه</label>
                  <LocationSelect value={collectionLocation} onChange={setCollectionLocation} locations={ctCollectionLocations} disabled={!commissionCurrency} />
                </div>
              )}
              <AccountPicker
                value={costCorrespondentAccount} onChange={setCostCorrespondentAccount} spec={ctCostCorrespondentSpec} label="حساب تكلفة العمولة (المراسل)"
                emptyMessage={!commissionCurrency ? 'اختر عملة العمولة أولاً' : 'لا حسابات مراسلين بعملة العمولة'}
              />
            </>
          )}

          {tab === 'REMIT_OUT' && (
            <>
              <div className="form-row">
                <div className="field">
                  <label className="field-label">الموقع المخصوم من العميل</label>
                  <LocationSelect value={fields.from_location_code ?? ''} onChange={(v) => setField('from_location_code', v)} locations={remitLocations} />
                </div>
                <AccountPicker
                  value={fields.partner_account_code ?? ''} onChange={(v) => setField('partner_account_code', v)}
                  spec={remitOutPartnerSpec} label="حساب المراسل"
                  emptyMessage={!fields.from_location_code ? 'اختر الموقع المخصوم أولاً' : 'لا حسابات مراسلين بالدولار في هذا الموقع'}
                />
              </div>
              <div className="form-row">
                <div className="field">
                  <label className="field-label">عملة المبلغ المُرسَل</label>
                  <CurrencySelect value={fields.currency_code ?? ''} onChange={(v) => setField('currency_code', v)} currencies={currencies} />
                </div>
                <AmountStage id="remit-amount" label={`المبلغ (${fields.currency_code || '—'})`} value={fields.amount ?? ''} onChange={(v) => setField('amount', v)} />
              </div>
              <div className="form-row">
                <div className="field field-rate">
                  <label className="field-label">سعر العميل</label>
                  <DecimalInput className="num" value={fields.client_rate ?? ''} onChange={(v) => setField('client_rate', v)} />
<DecimalError value={fields.client_rate ?? ''} />
                </div>
                <div className="field field-rate">
                  <label className="field-label">سعر التكلفة</label>
                  <DecimalInput className="num" value={fields.cost_rate ?? ''} onChange={(v) => setField('cost_rate', v)} />
<DecimalError value={fields.cost_rate ?? ''} />
                  <span className="rate-hint">سعر التكلفة داخلي — لا يظهر للعميل أبداً</span>
                </div>
              </div>
              {remitPreview && (
                <div className={`rate-direction ${remitPreview.diff.gte(0) ? 'money-positive' : 'money-negative'}`}>
                  {rateDirectionHint(remitPreview.diff).text}
                </div>
              )}
              {remitPreview && (
                <div className="result-card">
                  <div className="result-row"><span>يُحصَّل من العميل</span><span className="num">{remitPreview.clientAmt.toString()} USD</span></div>
                  <div className="result-row result-dashed"><span>التكلفة (داخلي)</span><span className="num text-muted">{remitPreview.costAmt.toString()} USD</span></div>
                  <div className="result-row result-final">
                    <span>{profitOrLossLabel(remitPreview.diff)} العملية</span>
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
              <div className="form-row">
                <AccountPicker value={fields.expense_account_code ?? ''} onChange={(v) => setField('expense_account_code', v)} spec={expenseCategorySpec} typeFilter={['EXPENSE']} label="بند المصروف" />
                <div className="field">
                  <label className="field-label">العملة</label>
                  <CurrencySelect value={fields.currency_code ?? ''} onChange={(v) => setField('currency_code', v)} currencies={currencies} />
                </div>
              </div>
              <AccountPicker
                value={fields.paying_account_code ?? ''} onChange={(v) => setField('paying_account_code', v)} spec={expensePayingSpec} label="الحساب المصروف منه"
                emptyMessage={!fields.currency_code ? 'اختر العملة أولاً' : 'لا صناديق/بنوك بهذه العملة'}
              />
              <div className="form-row">
                <AmountStage id="expense-amount" label="المبلغ" value={fields.amount ?? ''} onChange={(v) => setField('amount', v)} currencyCode={fields.currency_code || undefined} />
                <div className="field">
                  <label className="field-label">البيان (إلزامي)</label>
                  <input value={fields.description ?? ''} onChange={(e) => setField('description', e.target.value)} />
                </div>
              </div>
            </>
          )}

          {tab === 'SWIFT_OUT' && (
            <>
              <AccountPicker
                value={fields.partner_account_code ?? ''} onChange={(v) => setField('partner_account_code', v)} spec={swiftOutPartnerSpec} label="حساب المراسل (تركيا)"
                emptyMessage="لا حسابات مراسلين بالدولار في تركيا — سجّل الشريك من شاشة الشركاء أولاً"
              />
              <div className="form-row">
                <AmountStage id="swiftout-amount" label="المبلغ (USD)" value={fields.amount ?? ''} onChange={(v) => setField('amount', v)} currencyCode="USD" />
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
                <SelectWrap>
                  <select value={fields.swift_movement_id ?? ''} onChange={(e) => setField('swift_movement_id', e.target.value)}>
                    <option value="" disabled>{pendingSwift.length ? 'اختر حركة' : 'لا حركات معلَّقة'}</option>
                    {pendingSwift.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.out_entry_no ?? m.id} — {m.amount} {m.currency_code} — {m.partner_name_ar ?? 'مراسل'}
                      </option>
                    ))}
                  </select>
                </SelectWrap>
              </div>
              <div className="form-row">
                <AmountStage id="swiftin-total" label="المبلغ الواصل" value={fields.total_amount ?? ''} onChange={(v) => setField('total_amount', v)} />
                <div className="field">
                  <label className="field-label">الرسوم الفعلية</label>
                  <DecimalInput className="num" placeholder="0" value={fields.fee_amount ?? ''} onChange={(v) => setField('fee_amount', v)} />
<DecimalError value={fields.fee_amount ?? ''} />
                </div>
              </div>
              <AccountPicker
                value={fields.receiving_account_code ?? ''} onChange={(v) => setField('receiving_account_code', v)} spec={swiftInReceivingSpec} label="الحساب المستقبِل"
                emptyMessage={`لا بنوك صينية بعملة ${swiftInCurrency} — سجّل البنك من شاشة الشركاء أولاً`}
              />
              <div className="field">
                <label className="field-label">سعر تحويل البنك للرمبي (اختياري)</label>
                <DecimalInput className="num" value={fields.bank_conversion_rate ?? ''} onChange={(v) => setField('bank_conversion_rate', v)} />
<DecimalError value={fields.bank_conversion_rate ?? ''} />
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
                <SelectWrap>
                  <select value={fields.swift_movement_id ?? ''} onChange={(e) => setField('swift_movement_id', e.target.value)}>
                    <option value="" disabled>{pendingSwift.length ? 'اختر حركة' : 'لا حركات معلَّقة'}</option>
                    {pendingSwift.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.out_entry_no ?? m.id} — {m.amount} {m.currency_code} — {m.partner_name_ar ?? 'مراسل'}
                      </option>
                    ))}
                  </select>
                </SelectWrap>
                {/* بلا حقل اختيار حساب مراسل إطلاقاً — يُشتق آلياً من partner_account_code
                    الذي تحمله الحركة المختارة نفسها (انظر submit()). أي اختيار
                    يدوي هنا خطر حقيقي: قد يُعيد المال لمراسل خاطئ. */}
                {fields.swift_movement_id && (
                  <span className="rate-hint">
                    حساب المراسل يُشتق تلقائياً من الحركة المختارة: {selectedReturnMovement?.partner_account_code ?? '—'}
                  </span>
                )}
              </div>
              <div className="form-row">
                <AmountStage id="swiftreturn-total" label="المبلغ المرتجع كاملاً" value={fields.total_amount ?? ''} onChange={(v) => setField('total_amount', v)} />
                <div className="field">
                  <label className="field-label">رسوم على العميل</label>
                  <DecimalInput className="num" placeholder="0" value={fields.return_fee_amount ?? ''} onChange={(v) => setField('return_fee_amount', v)} />
<DecimalError value={fields.return_fee_amount ?? ''} />
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
              <FormGuide tone="info">نقل داخلي بين حسابات الشركة فقط — لا يمسّ أي حساب عميل إطلاقاً.</FormGuide>
              <div className="field">
                <label className="field-label">العملة</label>
                <CurrencySelect value={fields.currency_code ?? ''} onChange={(v) => setField('currency_code', v)} currencies={currencies} />
              </div>
              <div className="form-row">
                <AccountPicker
                  value={fields.from_account_code ?? ''} onChange={(v) => setField('from_account_code', v)} spec={localMoveFromSpec} label="من حساب"
                  emptyMessage={!fields.currency_code ? 'اختر العملة أولاً' : 'لا حسابات شركة بهذه العملة'}
                />
                <AccountPicker
                  value={fields.to_account_code ?? ''} onChange={(v) => setField('to_account_code', v)} spec={localMoveToSpec} label="إلى حساب"
                  emptyMessage={!fields.currency_code ? 'اختر العملة أولاً' : 'لا حسابات شركة بهذه العملة'}
                />
              </div>
              <div className="form-row">
                <AmountStage id="localmove-amount" label="المبلغ" value={fields.amount ?? ''} onChange={(v) => setField('amount', v)} currencyCode={fields.currency_code || undefined} />
                <div className="field">
                  <label className="field-label">رسوم (اختياري — تُقيَّد في 5200)</label>
                  <DecimalInput className="num" placeholder="0" value={fields.fee_amount ?? ''} onChange={(v) => setField('fee_amount', v)} />
<DecimalError value={fields.fee_amount ?? ''} />
                </div>
              </div>
            </>
          )}

          {tab === 'OPENING' && (
            <>
              <div className="choice-row">
                <label className="check-row">
                  <input type="radio" name="opening-mode" checked={openingAccountMode === 'system'} onChange={() => setOpeningAccountMode('system')} />
                  حساب نظامي
                </label>
                <label className="check-row">
                  <input type="radio" name="opening-mode" checked={openingAccountMode === 'client'} onChange={() => setOpeningAccountMode('client')} disabled={!client} />
                  حساب عميل {!client && '(اختر عميلاً من العمود الأيمن أولاً)'}
                </label>
              </div>
              {openingAccountMode === 'system' ? (
                // استثناء مقصود — لا تصفية عبر /reference/accounts/for-operation هنا:
                // رصيد افتتاحي قد يمسّ أي حساب في الشجرة، فتضييق الاختيار كان
                // سيمنع حالات مشروعة لا يمكن حصرها مسبقاً (انظر توثيق الاستثناء
                // الكامل في app/engine/account_filters.py).
                <AccountPicker value={fields.account_code ?? ''} onChange={(v) => setField('account_code', v)} spec={fullAccountListSpec} label="الحساب" />
              ) : (
                <div className="field">
                  <label className="field-label">حساب العميل (يجب أن يكون موجوداً فعلاً)</label>
                  <SelectWrap>
                    <select value={fields.account_code ?? ''} onChange={(e) => setField('account_code', e.target.value)}>
                      <option value="" disabled>{clientBalancesForOpening.length ? 'اختر حساباً' : 'لا حسابات بعد لهذا العميل'}</option>
                      {clientBalancesForOpening.map((b) => (
                        <option key={b.account_code} value={b.account_code}>{b.currency_code} — {b.location_code} ({b.account_code})</option>
                      ))}
                    </select>
                  </SelectWrap>
                </div>
              )}
              <div className="form-row">
                <div className="field">
                  <label className="field-label">العملة</label>
                  <CurrencySelect value={fields.currency_code ?? ''} onChange={(v) => setField('currency_code', v)} currencies={currencies} />
                </div>
                <AmountStage id="opening-amount" label="المبلغ" value={fields.amount ?? ''} onChange={(v) => setField('amount', v)} currencyCode={fields.currency_code || undefined} />
                <div className="field">
                  <label className="field-label">التاريخ (يقبل الماضي بحرّية في الفترة التأسيسية)</label>
                  <input type="date" value={fields.as_of_date ?? ''} onChange={(e) => setField('as_of_date', e.target.value)} />
                </div>
              </div>
              <div className="choice-row">
                <label className="check-row">
                  <input type="radio" name="opening-side" checked={fields.is_debit === 'true'} onChange={() => setField('is_debit', 'true')} />مدين
                </label>
                <label className="check-row">
                  <input type="radio" name="opening-side" checked={fields.is_debit === 'false'} onChange={() => setField('is_debit', 'false')} />دائن
                </label>
              </div>
              <div className="form-row">
                <div className="field">
                  <label className="field-label">مصدر الرصيد</label>
                  <SelectWrap>
                    <select value={fields.source_type ?? ''} onChange={(e) => setField('source_type', e.target.value)}>
                      <option value="" disabled>اختر</option>
                      <option value="VERIFIED">مُتحقَّق منه</option>
                      <option value="RECONSTRUCTED">مُعاد بناؤه</option>
                      <option value="KNOWN_BALANCE">رصيد معروف</option>
                      <option value="ADJUSTMENT">تسوية</option>
                    </select>
                  </SelectWrap>
                </div>
                <div className="field">
                  <label className="field-label">درجة الثقة (تُحدِّد الطرف المقابل تلقائياً)</label>
                  <SelectWrap>
                    <select value={fields.confidence ?? ''} onChange={(e) => setField('confidence', e.target.value)}>
                      <option value="" disabled>اختر</option>
                      <option value="HIGH">عالية → 3100 رأس المال</option>
                      <option value="MEDIUM">متوسطة → 3900 فروق تأسيسية</option>
                      <option value="LOW">منخفضة → 3900 فروق تأسيسية</option>
                    </select>
                  </SelectWrap>
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
              <AccountPicker value={fields.account_code ?? ''} onChange={(v) => setField('account_code', v)} spec={fullAccountListSpec} label="الحساب" />
              <div className="form-row">
                <div className="field">
                  <label className="field-label">العملة</label>
                  <CurrencySelect value={fields.currency_code ?? ''} onChange={(v) => setField('currency_code', v)} currencies={currencies} />
                </div>
                <AmountStage id="adjustment-amount" label="المبلغ" value={fields.amount ?? ''} onChange={(v) => setField('amount', v)} currencyCode={fields.currency_code || undefined} />
              </div>
              <div className="choice-row">
                <label className="check-row">
                  <input type="radio" name="adj-side" checked={fields.is_debit === 'true'} onChange={() => setField('is_debit', 'true')} />
                  زيادة في الصندوق (فائض جرد)
                </label>
                <label className="check-row">
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

          {(tab === 'RECEIPT' || tab === 'PAYMENT' || tab === 'EXCHANGE') && (
            <div className="form-row">
              <AmountStage id="op-amount" label="المبلغ" value={amount} onChange={setAmount} currencyCode={currencyCode || undefined} />
              {tab === 'EXCHANGE' && (
                <>
                  <div className="field field-rate">
                    <label className="field-label">{exchangeScope === 'TREASURY' ? 'سعر التنفيذ' : 'سعر العميل'}</label>
                    <DecimalInput className="num" value={clientRate} onChange={setClientRate} />
<DecimalError value={clientRate} />
                  </div>
                  {exchangeScope === 'CLIENT' && (
                    <div className="field field-rate">
                      <label className="field-label">سعر التكلفة</label>
                      <DecimalInput className="num" value={costRate} onChange={setCostRate} />
<DecimalError value={costRate} />
                      <span className="rate-hint">سعر التكلفة داخلي — لا يظهر للعميل أبداً</span>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {tab === 'EXCHANGE' && exchangePreview && (
            <div className={`rate-direction ${exchangePreview.diff.gte(0) ? 'money-positive' : 'money-negative'}`}>
              {rateDirectionHint(exchangePreview.diff).text}
            </div>
          )}

          {tab === 'EXCHANGE' && exchangePreview && (
            <div className="result-card">
              <div className="result-row"><span>المبلغ الناتج للعميل</span><span className="num">{exchangePreview.clientAmt.toString()} {toCurrency}</span></div>
              <div className="result-row result-dashed"><span>مبلغ التكلفة (داخلي)</span><span className="num text-muted">{exchangePreview.costAmt.toString()} {toCurrency}</span></div>
              <div className="result-row result-final">
                <span>{profitOrLossLabel(exchangePreview.diff)} العملية</span>
                <span className={`num ${exchangePreview.diff.gte(0) ? 'money-positive' : 'money-negative'}`}>
                  {exchangePreview.diff.toString()} {toCurrency}
                </span>
              </div>
            </div>
          )}

          {tab === 'EXCHANGE' && treasuryPreview && (
            <ExchangeSummary
              fromAmount={amount} fromCurrency={currencyCode} fromAccount={treasurySourceName || treasurySourceAccount || '—'}
              toAmount={treasuryPreview.toAmount.toString()} toCurrency={toCurrency} toAccount={treasuryDestName || treasuryDestAccount || '—'}
              rate={clientRate}
            />
          )}

          {tab === 'EXCHANGE' && exchangePreview && exchangePreview.diff.lt(0) && (
            <div className="field">
              <label className="field-label">سبب الهامش السالب (إلزامي)</label>
              <input value={negativeMarginReason} onChange={(e) => setNegativeMarginReason(e.target.value)} />
            </div>
          )}

          <div className="field">
            <label className="field-label" htmlFor="op-note">ملاحظة (اختياري)</label>
            <textarea
              id="op-note" value={fields.note ?? ''} onChange={(e) => setField('note', e.target.value)}
              rows={2} placeholder="تظهر في الإيصال وكشف الحساب"
            />
          </div>

          {isEdit && (
            <div className="field">
              <label className="field-label" htmlFor="edit-reason">سبب التعديل (إلزامي)</label>
              <textarea
                id="edit-reason" value={editReason} onChange={(e) => setEditReason(e.target.value)}
                rows={2} placeholder="لماذا يُعدَّل هذا القيد؟"
              />
            </div>
          )}

          {error && <FormGuide tone="critical">{error}</FormGuide>}
          {negOverride && (
            <FormGuide tone="critical">
              <div>سيصبح رصيد الحساب سالباً — هذا مسموح لكن يتطلب سبباً مكتوباً (مدير فقط، يُسجَّل في تقرير تجاوزات الرصيد).</div>
              <textarea
                value={negReason} onChange={(e) => setNegReason(e.target.value)} rows={2} autoFocus
                placeholder="سبب تجاوز الرصيد — مثلاً: صرف عاجل قبل تغطية الصندوق"
              />
              <div className="form-row">
                <button type="button" className="btn btn-secondary" onClick={() => setNegOverride(null)}>تراجع</button>
                <button
                  type="button" className="btn btn-primary" style={{ flex: 1 }}
                  disabled={busy || !negReason.trim()} onClick={() => void confirmNegativeOverride()}
                >
                  تأكيد الترحيل رغم الرصيد السالب
                </button>
              </div>
            </FormGuide>
          )}
          {backdateOverride && (
            <FormGuide tone="warning">
              <div>الفترة الشهرية لهذا التاريخ مقفلة — القيد بأثر رجعي مسموح لمديرك الحالي لكن يتطلب سبباً مكتوباً.</div>
              <textarea
                value={backdateOverrideReason} onChange={(e) => setBackdateOverrideReason(e.target.value)} rows={2} autoFocus
                placeholder="سبب القيد بأثر رجعي — مثلاً: تصحيح سهو مكتشف بعد الإقفال"
              />
              <div className="form-row">
                <button type="button" className="btn btn-secondary" onClick={() => setBackdateOverride(null)}>تراجع</button>
                <button
                  type="button" className="btn btn-primary" style={{ flex: 1 }}
                  disabled={busy || !backdateOverrideReason.trim()} onClick={() => void confirmBackdateOverride()}
                >
                  تأكيد الترحيل بأثر رجعي
                </button>
              </div>
            </FormGuide>
          )}
          {!isEdit && success && (
            <FormGuide tone="success">
              تم الترحيل — {success.entry_no}
              {success.profit_amount && ` — ربح ${success.profit_amount} ${success.profit_currency}`}
            </FormGuide>
          )}

          <div className="command-bar">
            <div className="command-hints">
              <span><kbd>Enter</kbd> {isEdit ? 'ترحيل التعديل' : 'حفظ وترحيل'}</span>
              {!isEdit && <span><kbd>Ctrl</kbd> + <kbd>Enter</kbd> حفظ وطباعة</span>}
              <span><kbd>Esc</kbd> إلغاء</span>
            </div>
            <div className="command-actions">
              {isEdit && (
                <button type="button" className="btn btn-secondary" onClick={onCancelEdit} disabled={busy}>تراجع</button>
              )}
              <button
                type="button" className="btn btn-primary btn-lg btn-post"
                disabled={busy || (needsClient && !client) || adminBlocked || (isEdit && !editReason.trim())}
                onClick={() => submit()}
              >
                {isEdit ? 'ترحيل التعديل' : 'حفظ وترحيل'}
              </button>
            </div>
          </div>
        </form>
      </div>
    </section>
  )
}
