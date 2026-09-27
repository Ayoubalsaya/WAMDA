import { Fragment, useEffect, useState } from 'react'
import { api } from '../api/client'
import { SegmentedTabs } from '../components/SegmentedTabs'
import type {
  AccountBalanceRow, BanksResponse, BoxesResponse, CorrespondentsResponse, Currency, CurrencyAmount, LotDetail, LotRow,
  PendingSwiftMovement,
} from '../api/types'
import { CurrencyBadge } from '../components/CurrencyBadge'
import { useReferenceData } from '../hooks/useReferenceData'
import { formatAmount, formatRate } from '../lib/formatAmount'
import './AccountsScreen.css'

type AccTab = 'boxes' | 'correspondents' | 'banks' | 'in-transit' | 'lots'

const TABS: { id: AccTab; label: string }[] = [
  { id: 'boxes', label: 'صناديق ليبيا' },
  { id: 'correspondents', label: 'مراسلو تركيا' },
  { id: 'banks', label: 'بنوك الصين' },
  { id: 'in-transit', label: 'في الطريق' },
  { id: 'lots', label: 'دفعات الرمبي' },
]

function TotalsRow({ totals, currencies }: { totals: CurrencyAmount[]; currencies: Currency[] }) {
  if (totals.length === 0) return null
  return (
    <div className="acc-totals-row">
      <span className="text-muted" style={{ fontSize: 12.5 }}>الإجمالي</span>
      {totals.map((t) => (
        <span key={t.currency_code} className="acc-total-chip">
          <span className="num" style={{ fontWeight: 700 }}>{formatAmount(t.amount, t.currency_code, currencies)}</span> <CurrencyBadge code={t.currency_code} />
        </span>
      ))}
    </div>
  )
}

function AccountsTable({ rows, currencies }: { rows: AccountBalanceRow[]; currencies: Currency[] }) {
  return (
    <table className="data-table">
      <thead><tr><th>الكود</th><th>الاسم</th><th>الرصيد</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.code}>
            <td className="num text-muted">{r.code}</td>
            <td>{r.name_ar}</td>
            <td className={`num ${Number(r.balance) < 0 ? 'money-negative' : ''}`} style={{ fontWeight: 600 }}>
              {formatAmount(r.balance, r.currency_code, currencies)} <CurrencyBadge code={r.currency_code} />
            </td>
          </tr>
        ))}
        {rows.length === 0 && <tr><td colSpan={3} className="text-muted">لا حسابات بعد</td></tr>}
      </tbody>
    </table>
  )
}

function BoxesTab({ currencies }: { currencies: Currency[] }) {
  const [data, setData] = useState<BoxesResponse | null>(null)
  useEffect(() => { void api.get<BoxesResponse>('/accounts/boxes').then(setData) }, [])
  if (!data) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <>
      <TotalsRow totals={data.totals} currencies={currencies} />
      <AccountsTable rows={data.accounts} currencies={currencies} />
    </>
  )
}

function CorrespondentsTab({ currencies }: { currencies: Currency[] }) {
  const [data, setData] = useState<CorrespondentsResponse | null>(null)
  useEffect(() => { void api.get<CorrespondentsResponse>('/accounts/correspondents').then(setData) }, [])
  if (!data) return <p className="text-muted">...جارٍ التحميل</p>
  if (data.groups.length === 0) return <p className="text-muted">لا حسابات مراسلين مسجَّلة في تركيا بعد — سجِّل شريكاً من شاشة الشركاء</p>
  return (
    <>
      <TotalsRow totals={data.totals} currencies={currencies} />
      {data.groups.map((g) => (
        <div key={g.partner_id ?? g.partner_name_ar} className="acc-partner-group">
          <div className="card-title" style={{ fontSize: 13.5, marginBottom: 6 }}>{g.partner_name_ar}</div>
          <AccountsTable rows={g.accounts} currencies={currencies} />
        </div>
      ))}
    </>
  )
}

function BanksTab({ currencies }: { currencies: Currency[] }) {
  const [data, setData] = useState<BanksResponse | null>(null)
  useEffect(() => { void api.get<BanksResponse>('/accounts/banks').then(setData) }, [])
  if (!data) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <>
      <TotalsRow totals={data.totals} currencies={currencies} />
      <AccountsTable rows={data.accounts} currencies={currencies} />
    </>
  )
}

function InTransitTab({ currencies }: { currencies: Currency[] }) {
  const [rows, setRows] = useState<PendingSwiftMovement[] | null>(null)
  useEffect(() => { void api.get<PendingSwiftMovement[]>('/reference/swift-movements/pending').then(setRows) }, [])
  if (!rows) return <p className="text-muted">...جارٍ التحميل</p>
  const today = new Date()
  return (
    <table className="data-table">
      <thead><tr><th>تاريخ الإرسال</th><th>الأيام في الطريق</th><th>المبلغ</th><th>المراسل</th><th>مرجع خارجي</th></tr></thead>
      <tbody>
        {rows.map((m) => {
          const days = Math.floor((today.getTime() - new Date(m.transfer_date).getTime()) / 86400000)
          return (
            <tr key={m.id}>
              <td className="num">{m.transfer_date}</td>
              <td className={`num ${days > 3 ? 'money-negative' : ''}`} style={{ fontWeight: 600 }}>{days}</td>
              <td className="num">{formatAmount(m.amount, m.currency_code, currencies)} <CurrencyBadge code={m.currency_code} /></td>
              <td>{m.partner_name_ar ?? '—'}</td>
              <td className="num text-muted">{m.external_ref ?? '—'}</td>
            </tr>
          )
        })}
        {rows.length === 0 && <tr><td colSpan={5} className="text-muted">لا تحويلات معلَّقة — كل شيء وصل</td></tr>}
      </tbody>
    </table>
  )
}

function LotsTab({ currencies }: { currencies: Currency[] }) {
  const [rows, setRows] = useState<LotRow[] | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<LotDetail | null>(null)

  useEffect(() => { void api.get<LotRow[]>('/lots').then(setRows) }, [])

  async function toggle(id: number) {
    if (expandedId === id) { setExpandedId(null); setDetail(null); return }
    setExpandedId(id)
    setDetail(null)
    const d = await api.get<LotDetail>(`/lots/${id}`)
    setDetail(d)
  }

  if (!rows) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>الدفعة</th><th>مرجع السويفت</th><th>تاريخ الوصول</th><th>الكمية الأصلية</th>
          <th>سعر التكلفة</th><th>المتبقي</th><th>عدد المبيعات</th><th>متوسط سعر البيع</th>
          <th>إجمالي الربح</th><th>الحالة</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((lot) => (
          <Fragment key={lot.id}>
            <tr className="acc-lot-row" onClick={() => void toggle(lot.id)}>
              <td className="num">{lot.lot_no}</td>
              <td className="num text-muted">{lot.swift_external_ref ?? '—'}</td>
              <td className="num">{lot.arrival_date}</td>
              <td className="num">{formatAmount(lot.original_qty, 'CNY', currencies)}</td>
              <td className="num">{formatRate(lot.cost_rate)}</td>
              <td className="num">
                {formatAmount(lot.remaining_qty, 'CNY', currencies)}
                <div className="lot-consumed-bar-track">
                  <div
                    className="lot-consumed-bar-fill"
                    style={{ width: `${100 - (Number(lot.remaining_qty) / Math.max(0.000001, Number(lot.original_qty))) * 100}%` }}
                  />
                </div>
              </td>
              <td className="num">{lot.num_sales}</td>
              <td className="num">{lot.weighted_avg_sale_rate ? formatRate(lot.weighted_avg_sale_rate) : '—'}</td>
              <td className={`num ${Number(lot.total_profit) >= 0 ? 'money-positive' : 'money-negative'}`} style={{ fontWeight: 700 }}>
                {lot.profit_currency ? formatAmount(lot.total_profit, lot.profit_currency, currencies) : lot.total_profit} {lot.profit_currency ?? ''}
              </td>
              <td><span className={`badge ${lot.status === 'OPEN' ? 'badge-chain' : 'badge-status-reversed'}`}>{lot.status}</span></td>
            </tr>
            {expandedId === lot.id && (
              <tr className="lot-detail-row">
                <td colSpan={10} style={{ background: 'var(--sky-50)', padding: 'var(--space-3)' }}>
                  {!detail && <p className="text-muted">...جارٍ التحميل</p>}
                  {detail && (
                    <table className="data-table">
                      <thead><tr><th>التاريخ</th><th>العميل</th><th>الكمية</th><th>سعر العميل</th><th>نصيب التكلفة</th><th>الربح</th></tr></thead>
                      <tbody>
                        {detail.consumptions.map((c, i) => (
                          <tr key={i}>
                            <td className="num">{c.consumed_at}</td>
                            <td>{c.client_name_ar ?? '—'}</td>
                            <td className="num">{formatAmount(c.qty, 'CNY', currencies)}</td>
                            <td className="num">{formatRate(c.client_rate)}</td>
                            <td className="num">{formatAmount(c.cost_share, c.profit_currency, currencies)}</td>
                            <td className={`num ${Number(c.profit) >= 0 ? 'money-positive' : 'money-negative'}`}>{formatAmount(c.profit, c.profit_currency, currencies)} {c.profit_currency}</td>
                          </tr>
                        ))}
                        {detail.consumptions.length === 0 && <tr><td colSpan={6} className="text-muted">لا استهلاكات بعد</td></tr>}
                      </tbody>
                    </table>
                  )}
                </td>
              </tr>
            )}
          </Fragment>
        ))}
        {rows.length === 0 && <tr><td colSpan={10} className="text-muted">لا دفعات رمبي بعد</td></tr>}
      </tbody>
    </table>
  )
}

export function AccountsScreen() {
  const [tab, setTab] = useState<AccTab>('boxes')
  const { currencies } = useReferenceData()
  return (
    <div className="journal-screen">
      <div className="op-row" style={{ justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 className="screen-title" style={{ margin: 0 }}>الحسابات</h2>
        {tab === 'correspondents' && (
          <a href="/documents/reports/correspondent-balances.pdf" target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">
            تنزيل PDF
          </a>
        )}
        {tab === 'boxes' && (
          <div style={{ display: 'flex', gap: 8 }}>
            <a href="/documents/reports/boxes-balances.xlsx" target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">
              تنزيل Excel
            </a>
            <a href="/documents/reports/boxes-balances.pdf" target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">
              تنزيل PDF
            </a>
          </div>
        )}
      </div>
      <div style={{ marginBottom: 12 }}>
        <SegmentedTabs variant="dock" ariaLabel="نوع الحساب" value={tab} onChange={setTab} items={TABS} />
      </div>
      <div className="card" style={{ overflowX: 'auto' }}>
        {tab === 'boxes' && <BoxesTab currencies={currencies} />}
        {tab === 'correspondents' && <CorrespondentsTab currencies={currencies} />}
        {tab === 'banks' && <BanksTab currencies={currencies} />}
        {tab === 'in-transit' && <InTransitTab currencies={currencies} />}
        {tab === 'lots' && <LotsTab currencies={currencies} />}
      </div>
    </div>
  )
}
