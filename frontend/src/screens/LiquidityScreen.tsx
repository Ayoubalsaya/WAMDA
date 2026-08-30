import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { LiquidityRow } from '../api/types'
import { CurrencyBadge } from '../components/CurrencyBadge'
import { useReferenceData } from '../hooks/useReferenceData'
import { formatAmount } from '../lib/formatAmount'
import './LiquidityScreen.css'

export function LiquidityScreen() {
  const [rows, setRows] = useState<LiquidityRow[] | null>(null)
  const { currencies } = useReferenceData()

  useEffect(() => {
    void api.get<LiquidityRow[]>('/position/liquidity').then(setRows)
  }, [])

  return (
    <div className="journal-screen">
      <h2 className="screen-title" style={{ marginBottom: 16 }}>مركز السيولة</h2>
      <div className="card">
        {!rows && <p className="text-muted">...جارٍ التحميل</p>}
        {rows && rows.length === 0 && <p className="text-muted">لا حسابات مرتبطة بموقع بعد</p>}
        {rows && rows.length > 0 && (
          <div className="liquidity-table-wrap">
            <table className="data-table liquidity-table">
              <thead>
                <tr><th>الموقع</th><th>أصولي</th><th>التزاماتي</th><th>الصافي</th><th></th></tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const net = Number(r.net)
                  return (
                    <tr key={`${r.currency_code}-${r.location_code}`} className="liquidity-row">
                      <td>
                        <CurrencyBadge code={r.currency_code} /> {r.location_name_ar}
                      </td>
                      <td className="num">{formatAmount(r.assets, r.currency_code, currencies)}</td>
                      <td className="num">{formatAmount(r.liabilities, r.currency_code, currencies)}</td>
                      <td className={`num liquidity-net ${net >= 0 ? 'money-positive' : 'money-negative'}`}>
                        {net >= 0 ? '+' : ''}{formatAmount(r.net, r.currency_code, currencies)} {net < 0 && '⚠'}
                      </td>
                      <td>
                        <div className="liquidity-bar-track">
                          <div
                            className={`liquidity-bar-fill ${net >= 0 ? 'is-positive' : 'is-negative'}`}
                            style={{ width: `${Math.min(100, (Math.abs(net) / Math.max(1, Math.abs(Number(r.assets)) + Math.abs(Number(r.liabilities)))) * 100)}%` }}
                          />
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="alert alert-info" style={{ marginTop: 16 }}>
        قد يكون إجمالي أرصدتك موجباً بينما المال في الموقع الخطأ — راجع كل
        صف بعملته وموقعه على حدة، لا الإجمالي وحده.
      </div>
    </div>
  )
}
