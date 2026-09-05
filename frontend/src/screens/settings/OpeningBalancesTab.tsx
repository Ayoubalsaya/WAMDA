import { useEffect, useState } from 'react'
import { api, ApiError, newIdempotencyKey } from '../../api/client'
import type { AccountOut, ClientSearchResult, Location, OpeningBalanceRow } from '../../api/types'

const SOURCE_TYPES: { v: string; label: string }[] = [
  { v: 'VERIFIED', label: 'مؤكَّد (مستند/كشف)' },
  { v: 'RECONSTRUCTED', label: 'مُعاد بناؤه من سجلّات' },
  { v: 'KNOWN_BALANCE', label: 'رصيد معروف بلا مستند' },
  { v: 'ADJUSTMENT', label: 'تسوية فرق تأسيسي' },
]
const CONFIDENCE: { v: string; label: string }[] = [
  { v: 'HIGH', label: 'عالية — الطرف المقابل ٣١٠٠ (رأس المال)' },
  { v: 'MEDIUM', label: 'متوسطة — الطرف المقابل ٣٩٠٠ (فروق تأسيسية)' },
  { v: 'LOW', label: 'منخفضة — الطرف المقابل ٣٩٠٠ (فروق تأسيسية)' },
]

export function OpeningBalancesTab() {
  const [accounts, setAccounts] = useState<AccountOut[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [rows, setRows] = useState<OpeningBalanceRow[] | null>(null)
  const [mode, setMode] = useState<'system' | 'client'>('system')
  const [accountCode, setAccountCode] = useState('')
  const [clientQuery, setClientQuery] = useState('')
  const [clientResults, setClientResults] = useState<ClientSearchResult[]>([])
  const [client, setClient] = useState<ClientSearchResult | null>(null)
  const [clientCurrency, setClientCurrency] = useState('LYD')
  const [clientLocation, setClientLocation] = useState('')
  const [amount, setAmount] = useState('')
  const [isDebit, setIsDebit] = useState(true)
  const [asOfDate, setAsOfDate] = useState('')
  const [sourceType, setSourceType] = useState('VERIFIED')
  const [confidence, setConfidence] = useState('HIGH')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)

  const selectedAccount = accounts.find((a) => a.code === accountCode)
  const currencyCode = mode === 'system' ? (selectedAccount?.currency_code ?? '') : clientCurrency

  async function reload() {
    setRows(await api.get<OpeningBalanceRow[]>('/periods/opening-balances'))
  }
  useEffect(() => {
    void api.get<AccountOut[]>('/reference/accounts').then(setAccounts)
    void api.get<Location[]>('/reference/locations').then((ls) => {
      setLocations(ls)
      if (ls[0]) setClientLocation(ls[0].code)
    })
    void reload()
  }, [])

  useEffect(() => {
    if (clientQuery.trim().length < 2) { setClientResults([]); return }
    const t = setTimeout(() => {
      void api.get<ClientSearchResult[]>(`/clients/search?q=${encodeURIComponent(clientQuery)}`).then(setClientResults)
    }, 250)
    return () => clearTimeout(t)
  }, [clientQuery])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!amount || !asOfDate || !currencyCode) return
    if (mode === 'system' && !accountCode) return
    if (mode === 'client' && (!client || !clientLocation)) return
    setBusy(true)
    setError(null)
    setOk(null)
    try {
      const body: Record<string, unknown> = {
        currency_code: currencyCode, amount, is_debit: isDebit, as_of_date: asOfDate,
        source_type: sourceType, confidence, source_note: note || undefined,
      }
      if (mode === 'system') body.account_code = accountCode
      else { body.client_id = client!.id; body.location_code = clientLocation }
      await api.post('/operations/opening', body, newIdempotencyKey())
      setOk(`سُجِّل رصيد ${mode === 'system' ? accountCode : client!.code} (${currencyCode}) — راجعه في الجدول أدناه`)
      setAmount(''); setNote('')
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر تسجيل الرصيد الافتتاحي')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-title" style={{ marginBottom: 12 }}>تسجيل رصيد افتتاحي</div>
        <div className="op-tabs" style={{ marginBottom: 12 }}>
          <button type="button" className={`op-tab${mode === 'system' ? ' is-active' : ''}`} onClick={() => setMode('system')}>حساب نظامي (صندوق/بنك/مراسل)</button>
          <button type="button" className={`op-tab${mode === 'client' ? ' is-active' : ''}`} onClick={() => setMode('client')}>حساب عميل</button>
        </div>
        <form onSubmit={submit}>
          {mode === 'system' ? (
            <div className="field" style={{ marginBottom: 10 }}>
              <label className="field-label" htmlFor="ob-acct">الحساب</label>
              <select id="ob-acct" value={accountCode} onChange={(e) => setAccountCode(e.target.value)} required>
                <option value="">اختر حساباً...</option>
                {accounts.map((a) => (
                  <option key={a.code} value={a.code}>
                    {a.code} — {a.name_ar}{a.currency_code ? ` (${a.currency_code})` : ''}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <div className="op-row" style={{ marginBottom: 10 }}>
              <div className="field" style={{ flex: 2, position: 'relative' }}>
                <label className="field-label" htmlFor="ob-client">العميل</label>
                <input
                  id="ob-client" value={client ? `${client.code} — ${client.name_ar}` : clientQuery}
                  onChange={(e) => { setClient(null); setClientQuery(e.target.value) }}
                  placeholder="ابحث بالاسم أو الكود" autoComplete="off" required
                />
                {!client && clientResults.length > 0 && (
                  <div style={{
                    position: 'absolute', top: '100%', insetInlineStart: 0, insetInlineEnd: 0, zIndex: 20,
                    background: 'var(--surface, #fff)', border: '1px solid var(--border, #e2e8f0)',
                    borderRadius: 8, marginTop: 2, maxHeight: 200, overflowY: 'auto',
                  }}>
                    {clientResults.map((c) => (
                      <button type="button" key={c.id}
                        style={{ display: 'block', width: '100%', textAlign: 'start', padding: '8px 10px',
                          background: 'none', border: 'none', cursor: 'pointer', fontSize: 13 }}
                        onClick={() => { setClient(c); setClientResults([]) }}>
                        {c.code} — {c.name_ar}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="field" style={{ flex: 1 }}>
                <label className="field-label" htmlFor="ob-cccy">العملة</label>
                <select id="ob-cccy" value={clientCurrency} onChange={(e) => setClientCurrency(e.target.value)}>
                  <option value="LYD">LYD</option><option value="USD">USD</option><option value="CNY">CNY</option>
                </select>
              </div>
              <div className="field" style={{ flex: 1 }}>
                <label className="field-label" htmlFor="ob-cloc">الموقع</label>
                <select id="ob-cloc" value={clientLocation} onChange={(e) => setClientLocation(e.target.value)}>
                  {locations.map((l) => <option key={l.code} value={l.code}>{l.name_ar}</option>)}
                </select>
              </div>
            </div>
          )}
          <div className="op-row" style={{ marginBottom: 10 }}>
            <div className="field" style={{ flex: 1 }}>
              <label className="field-label" htmlFor="ob-amt">المبلغ ({currencyCode || '—'})</label>
              <input id="ob-amt" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} required />
            </div>
            <div className="field" style={{ flex: 1 }}>
              <label className="field-label" htmlFor="ob-dir">الاتجاه</label>
              <select id="ob-dir" value={isDebit ? 'd' : 'c'} onChange={(e) => setIsDebit(e.target.value === 'd')}>
                <option value="d">رصيد مدين</option>
                <option value="c">رصيد دائن</option>
              </select>
            </div>
          </div>
          <div className="op-row" style={{ marginBottom: 10 }}>
            <div className="field" style={{ flex: 1 }}>
              <label className="field-label" htmlFor="ob-date">بتاريخ</label>
              <input id="ob-date" type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} required />
            </div>
            <div className="field" style={{ flex: 1.4 }}>
              <label className="field-label" htmlFor="ob-src">المصدر</label>
              <select id="ob-src" value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
                {SOURCE_TYPES.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
              </select>
            </div>
            <div className="field" style={{ flex: 1.6 }}>
              <label className="field-label" htmlFor="ob-conf">درجة الثقة</label>
              <select id="ob-conf" value={confidence} onChange={(e) => setConfidence(e.target.value)}>
                {CONFIDENCE.map((c) => <option key={c.v} value={c.v}>{c.label}</option>)}
              </select>
            </div>
          </div>
          <div className="field" style={{ marginBottom: 12 }}>
            <label className="field-label" htmlFor="ob-note">ملاحظة المصدر (اختيارية)</label>
            <input id="ob-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="مثلاً: كشف بنك الصين ٢٠٢٦-٠١-٠١" />
          </div>
          {error && <div className="alert alert-critical" style={{ marginBottom: 10 }}>{error}</div>}
          {ok && <div className="alert alert-info" style={{ marginBottom: 10 }}>{ok}</div>}
          <button type="submit" className="btn btn-primary" disabled={busy}>تسجيل الرصيد الافتتاحي</button>
        </form>
      </div>

      <div className="card">
        <div className="card-title" style={{ marginBottom: 12 }}>الأرصدة الافتتاحية المُدخَلة ({rows?.length ?? 0})</div>
        {!rows ? <p className="text-muted">...جارٍ التحميل</p> : rows.length === 0 ? (
          <p className="text-muted">لا أرصدة افتتاحية مُدخَلة بعد</p>
        ) : (
          <table className="data-table">
            <thead><tr>
              <th>الحساب</th><th>العملة</th><th>المبلغ</th><th>التاريخ</th>
              <th>المصدر</th><th>الثقة</th><th>الطرف المقابل</th><th>ملاحظة</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.account_code} — {r.account_name_ar}</td>
                  <td className="num">{r.currency_code}</td>
                  <td className="num" style={{ fontWeight: 600 }}>{r.amount}</td>
                  <td className="num">{r.as_of_date}</td>
                  <td>{SOURCE_TYPES.find((s) => s.v === r.source_type)?.label ?? r.source_type}</td>
                  <td>{r.confidence}</td>
                  <td className="num">{r.contra_account_code}</td>
                  <td className="text-muted">{r.source_note ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
