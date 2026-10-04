import { useEffect, useState } from 'react'
import { AlertTriangle, AlertCircle, Info } from 'lucide-react'
import { api } from '../api/client'
import type { Currency, DashboardSummary } from '../api/types'
import { CurrencyBadge } from '../components/CurrencyBadge'
import { useReferenceData } from '../hooks/useReferenceData'
import { formatAmount } from '../lib/formatAmount'
import './DashboardScreen.css'

const OP_LABELS: Record<string, string> = {
  RECEIPT: 'قبض', PAYMENT: 'صرف', EXCHANGE: 'صرافة', CASH_TRANSFER: 'تحويل بعمولة',
  LOCAL_MOVE: 'نقل داخلي', REMIT_OUT: 'إرسال خارجي', SWIFT_OUT: 'سويفت خروج', SWIFT_IN: 'سويفت وصول',
  SWIFT_RETURN: 'سويفت مرتجع', EXPENSE: 'مصروف', OPENING: 'رصيد افتتاحي', ADJUSTMENT: 'تسوية',
}

const SEVERITY_ICON: Record<string, typeof AlertTriangle> = { critical: AlertCircle, warning: AlertTriangle, info: Info }
const SEVERITY_CLASS: Record<string, string> = { critical: 'alert-critical', warning: 'alert-warning', info: 'alert-info' }

function ProfitColumn({
  title, rows, currencies,
}: { title: string; rows: { currency_code: string; amount: string }[]; currencies: Currency[] }) {
  return (
    <div className="profit-col">
      <div className="text-muted" style={{ fontSize: 'var(--fs-xs)', marginBottom: 8 }}>{title}</div>
      {rows.length === 0 && <div className="text-muted" style={{ fontSize: 'var(--fs-sm)' }}>لا شيء اليوم</div>}
      {rows.map((r) => (
        <div key={r.currency_code} className="profit-row">
          <span className={`num ${Number(r.amount) >= 0 ? 'money-positive' : 'money-negative'}`} style={{ fontSize: 'var(--fs-h3)', fontWeight: 700 }}>
            {formatAmount(r.amount, r.currency_code, currencies)}
          </span>
          <CurrencyBadge code={r.currency_code} />
        </div>
      ))}
    </div>
  )
}

export function DashboardScreen() {
  const [data, setData] = useState<DashboardSummary | null>(null)
  const { currencies } = useReferenceData()

  useEffect(() => {
    void api.get<DashboardSummary>('/dashboard/summary').then(setData)
  }, [])

  if (!data) return <div className="journal-screen"><p className="text-muted">...جارٍ التحميل</p></div>

  const maxClientBalance = Math.max(1, ...data.top_clients.map((c) => c.operation_count))

  return (
    <div className="journal-screen">
      <h2 className="screen-title" style={{ marginBottom: 16 }}>لوحة التحكم</h2>

      <div className="kpi-grid" style={{ marginBottom: 16 }}>
        {data.kpis.funds.map((f) => (
          <div className="card kpi-card" key={`funds-${f.currency_code}`}>
            <div className="text-muted" style={{ fontSize: 'var(--fs-xs)' }}>أرصدة الصناديق والمراسلين والبنوك</div>
            <div className="num kpi-value">{formatAmount(f.amount, f.currency_code, currencies)}</div>
            <div style={{ marginTop: 4 }}><CurrencyBadge code={f.currency_code} /></div>
          </div>
        ))}
        {data.kpis.client_debts.map((d) => (
          <div className="card kpi-card" key={`debt-${d.currency_code}`} data-testid="kpi-client-debts">
            <div className="text-muted" style={{ fontSize: 'var(--fs-xs)' }}>ديون العملاء لنا</div>
            <div className="num kpi-value money-negative">{formatAmount(d.amount, d.currency_code, currencies)}</div>
            <div style={{ marginTop: 4 }}><CurrencyBadge code={d.currency_code} /></div>
          </div>
        ))}
        {data.kpis.client_liabilities.map((l) => (
          <div className="card kpi-card" key={`liab-${l.currency_code}`}>
            <div className="text-muted" style={{ fontSize: 'var(--fs-xs)' }}>التزامات العملاء</div>
            <div className="num kpi-value">{formatAmount(l.amount, l.currency_code, currencies)}</div>
            <div style={{ marginTop: 4 }}><CurrencyBadge code={l.currency_code} /></div>
          </div>
        ))}
      </div>

      <div className="dashboard-mid-row" style={{ marginBottom: 16 }}>
        <div className="card">
          <div className="card-title" style={{ marginBottom: 12 }}>أرباح اليوم</div>
          <div className="profit-columns">
            <ProfitColumn title="فرق التحويل" rows={data.today_profit.transfer_fee} currencies={currencies} />
            <ProfitColumn title="فروق أسعار صرف العملاء" rows={data.today_profit.exchange_spread} currencies={currencies} />
            <ProfitColumn title="عمولة الصرافة (+إيراد / −مصروف)" rows={data.today_profit.exchange_commission} currencies={currencies} />
            <ProfitColumn title="الصافي (لكل عملة، يشمل العمولة)" rows={data.today_profit.net_by_currency} currencies={currencies} />
          </div>
        </div>
        <div className="card">
          <div className="card-title" style={{ marginBottom: 12 }}>تنبيهات</div>
          {data.alerts.length === 0 && <div className="text-muted" style={{ fontSize: 'var(--fs-sm)' }}>لا تنبيهات حالياً</div>}
          <div className="alerts-list">
            {data.alerts.map((a, i) => {
              const Icon = SEVERITY_ICON[a.severity] ?? Info
              return (
                <div key={i} className={`alert ${SEVERITY_CLASS[a.severity] ?? 'alert-info'}`}>
                  <Icon size={16} strokeWidth={1.9} />
                  <span style={{ fontSize: 'var(--fs-sm)' }}>{a.message_ar}</span>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      <div className="dashboard-bottom-row">
        <div className="card">
          <div className="card-title" style={{ marginBottom: 12 }}>آخر العمليات</div>
          <table className="data-table">
            <thead><tr><th>التاريخ</th><th>النوع</th><th>العميل</th><th>الحالة</th><th>الربح</th></tr></thead>
            <tbody>
              {data.recent_entries.map((e) => (
                <tr key={e.id}>
                  <td className="num">{e.entry_date}</td>
                  <td>{OP_LABELS[e.operation_type] ?? e.operation_type}</td>
                  <td>{e.client_name_ar ?? '—'}</td>
                  <td><span className={`badge badge-status-${e.status.toLowerCase()}`}>{e.status}</span></td>
                  <td className="num">
                    {e.profit_amount && e.profit_currency ? (
                      <span className={Number(e.profit_amount) >= 0 ? 'money-positive' : 'money-negative'}>
                        {formatAmount(e.profit_amount, e.profit_currency, currencies)} {e.profit_currency}
                      </span>
                    ) : '—'}
                  </td>
                </tr>
              ))}
              {data.recent_entries.length === 0 && (
                <tr><td colSpan={5} className="text-muted">لا عمليات بعد</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="card">
          <div className="card-title" style={{ marginBottom: 12 }}>أفضل ٥ عملاء</div>
          {data.top_clients.length === 0 && <div className="text-muted" style={{ fontSize: 'var(--fs-sm)' }}>لا بيانات كافية بعد</div>}
          <div className="top-clients-list">
            {data.top_clients.map((c) => (
              <div key={c.client_id} className="top-client-row">
                <div className="top-client-info">
                  <span>{c.name_ar}</span>
                  <span className="num text-muted" style={{ fontSize: 'var(--fs-xs)' }}>{c.code}</span>
                </div>
                <div className="top-client-bar-track">
                  <div className="top-client-bar-fill" style={{ width: `${(c.operation_count / maxClientBalance) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
