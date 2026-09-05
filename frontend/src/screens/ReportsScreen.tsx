import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type {
  ActivityRow, BalanceOverrideRow, ClientProfitabilityRow, CorrespondentActivityRow, Currency, CurrencyAmount,
  DebtsByCurrencyRow, EmergencyEntryRow, FoundingReconciliationResponse, IncomeStatementResponse,
  LossMakingEntryRow, ProfitByPeriodRow, SwiftHistoryRow, TrialBalanceResponse,
} from '../api/types'
import { CurrencyBadge } from '../components/CurrencyBadge'
import { useReferenceData } from '../hooks/useReferenceData'
import { formatAmount } from '../lib/formatAmount'
import './ReportsScreen.css'

type ReportId =
  | 'debts' | 'profit-period' | 'trial-balance' | 'income-statement' | 'client-profitability'
  | 'lot-profitability' | 'activity-currency' | 'activity-month' | 'correspondent-activity'
  | 'swift-history' | 'loss-making' | 'balance-overrides' | 'emergency-entries' | 'founding-reconciliation'

const REPORTS: { id: ReportId; label: string }[] = [
  { id: 'debts', label: 'الديون لكل عملة' },
  { id: 'profit-period', label: 'الأرباح حسب الفترة' },
  { id: 'trial-balance', label: 'ميزان المراجعة' },
  { id: 'income-statement', label: 'قائمة الدخل' },
  { id: 'client-profitability', label: 'ربحية العملاء' },
  { id: 'lot-profitability', label: 'ربحية الدفعات' },
  { id: 'activity-currency', label: 'أكثر العملات حركة' },
  { id: 'activity-month', label: 'أكثر الأشهر حركة' },
  { id: 'correspondent-activity', label: 'حركة المراسلين' },
  { id: 'swift-history', label: 'السويفت' },
  { id: 'loss-making', label: 'العمليات الخاسرة' },
  { id: 'balance-overrides', label: 'تجاوزات الرصيد' },
  { id: 'emergency-entries', label: 'قيود الطوارئ' },
  { id: 'founding-reconciliation', label: 'المصالحة التأسيسية' },
]

function AmountChips({ items, currencies }: { items: CurrencyAmount[]; currencies: Currency[] }) {
  if (items.length === 0) return <span className="text-muted">—</span>
  return (
    <>
      {items.map((c) => (
        <span key={c.currency_code} className="report-amount-chip">
          <span className={`num ${Number(c.amount) < 0 ? 'money-negative' : ''}`}>{formatAmount(c.amount, c.currency_code, currencies)}</span>{' '}
          <CurrencyBadge code={c.currency_code} />
        </span>
      ))}
    </>
  )
}

function DebtsByCurrencyTab({ currencies }: { currencies: Currency[] }) {
  const [rows, setRows] = useState<DebtsByCurrencyRow[] | null>(null)
  useEffect(() => { void api.get<DebtsByCurrencyRow[]>('/reports/debts-by-currency').then(setRows) }, [])
  if (!rows) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <table className="data-table">
      <thead><tr><th>العملة</th><th>إجمالي المديونية</th><th>عدد العملاء</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.currency_code}>
            <td><CurrencyBadge code={r.currency_code} /></td>
            <td className="num" style={{ fontWeight: 700 }}>{formatAmount(r.total_owed, r.currency_code, currencies)}</td>
            <td className="num">{r.client_count}</td>
          </tr>
        ))}
        {rows.length === 0 && <tr><td colSpan={3} className="text-muted">لا مديونيات حالياً</td></tr>}
      </tbody>
    </table>
  )
}

function ProfitByPeriodTab({ currencies }: { currencies: Currency[] }) {
  const [granularity, setGranularity] = useState<'weekly' | 'monthly' | 'yearly'>('monthly')
  const [rows, setRows] = useState<ProfitByPeriodRow[] | null>(null)
  useEffect(() => {
    setRows(null)
    void api.get<ProfitByPeriodRow[]>(`/reports/profit-by-period?granularity=${granularity}`).then(setRows)
  }, [granularity])
  return (
    <>
      <div className="op-tabs" style={{ marginBottom: 12 }}>
        {(['weekly', 'monthly', 'yearly'] as const).map((g) => (
          <button key={g} type="button" className={`op-tab${granularity === g ? ' is-active' : ''}`} onClick={() => setGranularity(g)}>
            {g === 'weekly' ? 'أسبوعي' : g === 'monthly' ? 'شهري' : 'سنوي'}
          </button>
        ))}
      </div>
      {!rows ? <p className="text-muted">...جارٍ التحميل</p> : (
        <table className="data-table">
          <thead><tr><th>الفترة</th><th>فرق التحويل</th><th>فروق الصرف</th><th>الصافي</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.period_label}>
                <td className="num">{r.period_label}</td>
                <td><AmountChips items={r.transfer_fee} currencies={currencies} /></td>
                <td><AmountChips items={r.exchange_spread} currencies={currencies} /></td>
                <td><AmountChips items={r.net_by_currency} currencies={currencies} /></td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={4} className="text-muted">لا أرباح مسجَّلة في هذه الفترات</td></tr>}
          </tbody>
        </table>
      )}
    </>
  )
}

function TrialBalanceTab({ currencies }: { currencies: Currency[] }) {
  const [data, setData] = useState<TrialBalanceResponse | null>(null)
  useEffect(() => { void api.get<TrialBalanceResponse>('/reports/trial-balance').then(setData) }, [])
  if (!data) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <>
      <div className="report-balanced-banner" data-balanced={data.balanced}>
        {data.balanced ? 'الميزان متوازن لكل عملة ✓' : 'تنبيه: الميزان غير متوازن — يستحق فحصاً فورياً'}
      </div>
      <div className="acc-totals-row" style={{ margin: '12px 0' }}>
        <span className="text-muted" style={{ fontSize: 12.5 }}>إجمالي مدين</span>
        <AmountChips items={data.total_debit_by_currency} currencies={currencies} />
        <span className="text-muted" style={{ fontSize: 12.5 }}>إجمالي دائن</span>
        <AmountChips items={data.total_credit_by_currency} currencies={currencies} />
      </div>
      <table className="data-table">
        <thead><tr><th>الكود</th><th>الحساب</th><th>النوع</th><th>العملة</th><th>مدين</th><th>دائن</th></tr></thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={r.account_code}>
              <td className="num text-muted">{r.account_code}</td>
              <td>{r.account_name_ar}</td>
              <td className="text-muted">{r.account_type}</td>
              <td>{r.currency_code ? <CurrencyBadge code={r.currency_code} /> : '—'}</td>
              <td className="num">{Number(r.debit) > 0 ? (r.currency_code ? formatAmount(r.debit, r.currency_code, currencies) : r.debit) : '—'}</td>
              <td className="num">{Number(r.credit) > 0 ? (r.currency_code ? formatAmount(r.credit, r.currency_code, currencies) : r.credit) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function IncomeStatementTab({ currencies }: { currencies: Currency[] }) {
  const [data, setData] = useState<IncomeStatementResponse | null>(null)
  useEffect(() => { void api.get<IncomeStatementResponse>('/reports/income-statement').then(setData) }, [])
  if (!data) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <>
      <div className="acc-totals-row" style={{ marginBottom: 16 }}>
        <span className="text-muted" style={{ fontSize: 12.5 }}>الصافي</span>
        <AmountChips items={data.net_by_currency} currencies={currencies} />
      </div>
      <div className="acc-partner-group">
        <div className="card-title" style={{ fontSize: 13.5, marginBottom: 6 }}>الإيرادات</div>
        <table className="data-table">
          <thead><tr><th>الكود</th><th>الحساب</th><th>العملة</th><th>المبلغ</th></tr></thead>
          <tbody>
            {data.revenue.map((r) => (
              <tr key={r.account_code}>
                <td className="num text-muted">{r.account_code}</td>
                <td>{r.account_name_ar}</td>
                <td><CurrencyBadge code={r.currency_code} /></td>
                <td className="num money-positive" style={{ fontWeight: 700 }}>{formatAmount(r.amount, r.currency_code, currencies)}</td>
              </tr>
            ))}
            {data.revenue.length === 0 && <tr><td colSpan={4} className="text-muted">لا إيرادات مسجَّلة</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="acc-partner-group">
        <div className="card-title" style={{ fontSize: 13.5, marginBottom: 6 }}>المصروفات</div>
        <table className="data-table">
          <thead><tr><th>الكود</th><th>الحساب</th><th>العملة</th><th>المبلغ</th></tr></thead>
          <tbody>
            {data.expense.map((r) => (
              <tr key={r.account_code}>
                <td className="num text-muted">{r.account_code}</td>
                <td>{r.account_name_ar}</td>
                <td><CurrencyBadge code={r.currency_code} /></td>
                <td className="num money-negative" style={{ fontWeight: 700 }}>{formatAmount(r.amount, r.currency_code, currencies)}</td>
              </tr>
            ))}
            {data.expense.length === 0 && <tr><td colSpan={4} className="text-muted">لا مصروفات مسجَّلة</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  )
}

function ClientProfitabilityTab({ currencies }: { currencies: Currency[] }) {
  const [rows, setRows] = useState<ClientProfitabilityRow[] | null>(null)
  useEffect(() => { void api.get<ClientProfitabilityRow[]>('/reports/client-profitability').then(setRows) }, [])
  if (!rows) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <table className="data-table">
      <thead><tr><th>العميل</th><th>الكود</th><th>عدد العمليات</th><th>الربح لكل عملة</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.client_id}>
            <td>{r.client_name_ar}</td>
            <td className="num text-muted">{r.client_code}</td>
            <td className="num">{r.operation_count}</td>
            <td><AmountChips items={r.profit_by_currency} currencies={currencies} /></td>
          </tr>
        ))}
        {rows.length === 0 && <tr><td colSpan={4} className="text-muted">لا عمليات مربحة مسجَّلة بعد</td></tr>}
      </tbody>
    </table>
  )
}

function ActivityTab({ endpoint, keyLabel }: { endpoint: string; keyLabel: string }) {
  const [rows, setRows] = useState<ActivityRow[] | null>(null)
  useEffect(() => { void api.get<ActivityRow[]>(endpoint).then(setRows) }, [endpoint])
  if (!rows) return <p className="text-muted">...جارٍ التحميل</p>
  const max = Math.max(1, ...rows.map((r) => r.entry_count))
  return (
    <table className="data-table">
      <thead><tr><th>{keyLabel}</th><th>عدد القيود</th><th></th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key}>
            <td className="num">{r.key}</td>
            <td className="num" style={{ fontWeight: 700 }}>{r.entry_count}</td>
            <td style={{ width: '40%' }}>
              <div className="lot-consumed-bar-track" style={{ width: '100%' }}>
                <div className="lot-consumed-bar-fill" style={{ width: `${(r.entry_count / max) * 100}%` }} />
              </div>
            </td>
          </tr>
        ))}
        {rows.length === 0 && <tr><td colSpan={3} className="text-muted">لا بيانات بعد</td></tr>}
      </tbody>
    </table>
  )
}

function CorrespondentActivityTab({ currencies }: { currencies: Currency[] }) {
  const [rows, setRows] = useState<CorrespondentActivityRow[] | null>(null)
  useEffect(() => { void api.get<CorrespondentActivityRow[]>('/reports/correspondent-activity').then(setRows) }, [])
  if (!rows) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <table className="data-table">
      <thead><tr><th>المراسل</th><th>عدد القيود</th><th>إجمالي مدين</th><th>إجمالي دائن</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.partner_id}>
            <td>{r.partner_name_ar}</td>
            <td className="num">{r.entry_count}</td>
            <td><AmountChips items={r.total_debit_by_currency} currencies={currencies} /></td>
            <td><AmountChips items={r.total_credit_by_currency} currencies={currencies} /></td>
          </tr>
        ))}
        {rows.length === 0 && <tr><td colSpan={4} className="text-muted">لا مراسلين مسجَّلين بعد</td></tr>}
      </tbody>
    </table>
  )
}

const SWIFT_STATUS_LABELS: Record<string, string> = { SENT: 'مُرسَل', RECEIVED: 'وصل', RETURNED: 'مرتجع' }

function SwiftHistoryTab({ currencies }: { currencies: Currency[] }) {
  const [rows, setRows] = useState<SwiftHistoryRow[] | null>(null)
  useEffect(() => { void api.get<SwiftHistoryRow[]>('/reports/swift-history').then(setRows) }, [])
  if (!rows) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <table className="data-table">
      <thead><tr><th>الحالة</th><th>المبلغ</th><th>تاريخ الإرسال</th><th>تاريخ الوصول</th><th>المراسل</th><th>مرجع خارجي</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}>
            <td><span className="badge badge-chain">{SWIFT_STATUS_LABELS[r.status] ?? r.status}</span></td>
            <td className="num">{formatAmount(r.amount, r.currency_code, currencies)} <CurrencyBadge code={r.currency_code} /></td>
            <td className="num">{r.transfer_date}</td>
            <td className="num">{r.received_date ?? '—'}</td>
            <td>{r.partner_name_ar ?? '—'}</td>
            <td className="num text-muted">{r.external_ref ?? '—'}</td>
          </tr>
        ))}
        {rows.length === 0 && <tr><td colSpan={6} className="text-muted">لا حركات سويفت بعد</td></tr>}
      </tbody>
    </table>
  )
}

const OP_LABELS: Record<string, string> = {
  RECEIPT: 'قبض', PAYMENT: 'صرف', EXCHANGE: 'صرافة', CASH_TRANSFER: 'تحويل بعمولة',
  LOCAL_MOVE: 'نقل داخلي', REMIT_OUT: 'إرسال لمستفيد', SWIFT_OUT: 'سويفت خروج', SWIFT_IN: 'سويفت وصول',
  SWIFT_RETURN: 'سويفت مرتجع', EXPENSE: 'مصروف', OPENING: 'رصيد افتتاحي', ADJUSTMENT: 'تسوية',
}

function LossMakingTab({ currencies }: { currencies: Currency[] }) {
  const [rows, setRows] = useState<LossMakingEntryRow[] | null>(null)
  useEffect(() => { void api.get<LossMakingEntryRow[]>('/reports/loss-making-operations').then(setRows) }, [])
  if (!rows) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <table className="data-table">
      <thead><tr><th>رقم القيد</th><th>التاريخ</th><th>النوع</th><th>العميل</th><th>الخسارة</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.entry_id}>
            <td className="num text-muted">{r.entry_no}</td>
            <td className="num">{r.entry_date}</td>
            <td>{OP_LABELS[r.operation_type] ?? r.operation_type}</td>
            <td>{r.client_name_ar ?? '—'}</td>
            <td className="num money-negative" style={{ fontWeight: 700 }}>{formatAmount(r.profit_amount, r.profit_currency, currencies)} <CurrencyBadge code={r.profit_currency} /></td>
          </tr>
        ))}
        {rows.length === 0 && <tr><td colSpan={5} className="text-muted">لا عمليات خاسرة — كل الهوامش موجبة</td></tr>}
      </tbody>
    </table>
  )
}

const OVERRIDE_ACTION_LABELS: Record<string, string> = {
  CREDIT_LIMIT_OVERRIDE: 'تجاوز حد ائتمان', NEGATIVE_BALANCE_OVERRIDE: 'تجاوز رصيد سالب',
}

function BalanceOverridesTab() {
  const [rows, setRows] = useState<BalanceOverrideRow[] | null>(null)
  useEffect(() => { void api.get<BalanceOverrideRow[]>('/reports/balance-overrides').then(setRows) }, [])
  if (!rows) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <table className="data-table">
      <thead><tr><th>التاريخ</th><th>النوع</th><th>الحساب</th><th>رقم القيد</th><th>السبب</th><th>بواسطة</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}>
            <td className="num">{new Date(r.created_at).toLocaleString('ar-LY')}</td>
            <td><span className="badge alert-warning">{OVERRIDE_ACTION_LABELS[r.action] ?? r.action}</span></td>
            <td className="num text-muted">{r.account_code ?? '—'}</td>
            <td className="num text-muted">{r.entry_no ?? '—'}</td>
            <td>{r.reason ?? '—'}</td>
            <td className="text-muted">{r.actor_username ?? '—'}</td>
          </tr>
        ))}
        {rows.length === 0 && <tr><td colSpan={6} className="text-muted">لا تجاوزات مسجَّلة</td></tr>}
      </tbody>
    </table>
  )
}

function EmergencyEntriesTab() {
  const [rows, setRows] = useState<EmergencyEntryRow[] | null>(null)
  useEffect(() => { void api.get<EmergencyEntryRow[]>('/reports/emergency-entries').then(setRows) }, [])
  if (!rows) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <table className="data-table">
      <thead><tr><th>رقم القيد</th><th>تاريخ القيد</th><th>النوع</th><th>وقت العملية الفعلي</th><th>سبب التأخير</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.entry_id}>
            <td className="num text-muted">{r.entry_no}</td>
            <td className="num">{r.entry_date}</td>
            <td>{OP_LABELS[r.operation_type] ?? r.operation_type}</td>
            <td className="num">{r.real_operation_time ? new Date(r.real_operation_time).toLocaleString('ar-LY') : '—'}</td>
            <td className="text-muted">{r.backdate_reason ?? '—'}</td>
          </tr>
        ))}
        {rows.length === 0 && <tr><td colSpan={5} className="text-muted">لا قيود طوارئ مسجَّلة</td></tr>}
      </tbody>
    </table>
  )
}

function FoundingReconciliationTab({ currencies }: { currencies: Currency[] }) {
  const [data, setData] = useState<FoundingReconciliationResponse | null>(null)
  useEffect(() => { void api.get<FoundingReconciliationResponse>('/reports/founding-reconciliation').then(setData) }, [])
  if (!data) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <div className="kpi-grid">
      <div className="card kpi-card">
        <div className="text-muted" style={{ fontSize: 12.5 }}>رصيد فروق التأسيس (٣٩٠٠)</div>
        <div className="num" style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>
          <AmountChips items={data.suspense_balance_by_currency} currencies={currencies} />
        </div>
      </div>
      <div className="card kpi-card">
        <div className="text-muted" style={{ fontSize: 12.5 }}>إجمالي الأرصدة الافتتاحية</div>
        <div className="num" style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>
          <AmountChips items={data.opening_balances_total_by_currency} currencies={currencies} />
        </div>
        <div className="text-muted" style={{ fontSize: 12, marginTop: 6 }}>{data.opening_balances_count} رصيد مُسجَّل</div>
      </div>
      <div className="card kpi-card">
        <div className="text-muted" style={{ fontSize: 12.5 }}>بنود مصالحة مفتوحة</div>
        <div className="num kpi-value">{data.open_reconciliation_items}</div>
      </div>
    </div>
  )
}

// تصدير PDF متاح فقط للتقارير التي لها مستند مطابق في `app/documents/reports_doc.py`
// (المرحلة ١٠) — بقية التقارير أعلاه تبقى عرض شاشة فقط حتى الآن.
const PDF_EXPORT_KEYS: Partial<Record<ReportId, string>> = {
  'trial-balance': 'trial-balance',
  'founding-reconciliation': 'founding-reconciliation',
  'balance-overrides': 'balance-overrides',
  'emergency-entries': 'emergency-entries',
  'lot-profitability': 'lot-profitability',
}

// §٨ — التقارير التي تنص الوثيقة على صيغة Excel لها (المرحلة ١٣)
const EXCEL_EXPORT_KEYS: Partial<Record<ReportId, string>> = {
  'trial-balance': 'trial-balance',
  'founding-reconciliation': 'founding-reconciliation',
  'lot-profitability': 'lot-profitability',
}

export function ReportsScreen() {
  const [report, setReport] = useState<ReportId>('debts')
  const { currencies } = useReferenceData()
  const exportKey = PDF_EXPORT_KEYS[report]
  const excelKey = EXCEL_EXPORT_KEYS[report]

  return (
    <div className="journal-screen reports-screen">
      <div className="op-row" style={{ justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 className="screen-title" style={{ margin: 0 }}>التقارير</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {excelKey && (
            <a href={`/documents/reports/${excelKey}.xlsx`} target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">
              تنزيل Excel
            </a>
          )}
          {exportKey && (
            <a href={`/documents/reports/${exportKey}.pdf`} target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">
              تنزيل PDF
            </a>
          )}
        </div>
      </div>
      <div className="reports-layout">
        <div className="reports-nav">
          {REPORTS.map((r) => (
            <button
              key={r.id} type="button"
              className={`reports-nav-item${report === r.id ? ' is-active' : ''}`}
              onClick={() => setReport(r.id)}
            >
              {r.label}
            </button>
          ))}
        </div>
        <div className="card reports-content" style={{ overflowX: 'auto' }}>
          {report === 'debts' && <DebtsByCurrencyTab currencies={currencies} />}
          {report === 'profit-period' && <ProfitByPeriodTab currencies={currencies} />}
          {report === 'trial-balance' && <TrialBalanceTab currencies={currencies} />}
          {report === 'income-statement' && <IncomeStatementTab currencies={currencies} />}
          {report === 'client-profitability' && <ClientProfitabilityTab currencies={currencies} />}
          {report === 'lot-profitability' && (
            <p className="text-muted">ربحية كل دفعة رمبي مُفصَّلة أصلاً في شاشة الحسابات ← دفعات الرمبي (كل دفعة سويفت بعينها بربحها وكل استهلاكاتها).</p>
          )}
          {report === 'activity-currency' && <ActivityTab endpoint="/reports/activity-by-currency" keyLabel="العملة" />}
          {report === 'activity-month' && <ActivityTab endpoint="/reports/activity-by-month" keyLabel="الشهر" />}
          {report === 'correspondent-activity' && <CorrespondentActivityTab currencies={currencies} />}
          {report === 'swift-history' && <SwiftHistoryTab currencies={currencies} />}
          {report === 'loss-making' && <LossMakingTab currencies={currencies} />}
          {report === 'balance-overrides' && <BalanceOverridesTab />}
          {report === 'emergency-entries' && <EmergencyEntriesTab />}
          {report === 'founding-reconciliation' && <FoundingReconciliationTab currencies={currencies} />}
        </div>
      </div>
    </div>
  )
}
