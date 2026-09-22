import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { AccountOut, CompanyProfile, PartnerRow, UserListRow } from '../api/types'
import { useReferenceData } from '../hooks/useReferenceData'
import { AuditLogTab } from './settings/AuditLogTab'
import { OpeningBalancesTab } from './settings/OpeningBalancesTab'
import { PeriodsTab } from './settings/PeriodsTab'
import './SettingsScreen.css'

type SettingsTab = 'company' | 'users' | 'partners' | 'bank-accounts' | 'opening-balances' | 'periods' | 'audit-log'

const TABS: { id: SettingsTab; label: string }[] = [
  { id: 'company', label: 'ملف الشركة' },
  { id: 'users', label: 'المستخدمون' },
  { id: 'partners', label: 'الشركاء' },
  { id: 'bank-accounts', label: 'الحسابات البنكية' },
  { id: 'opening-balances', label: 'الأرصدة الافتتاحية' },
  { id: 'periods', label: 'الفترات المحاسبية' },
  { id: 'audit-log', label: 'سجل التدقيق' },
]

const PARTNER_ACCOUNT_PARENTS = [
  { code: '1310', label: 'مراسل ليبيا' },
  { code: '1320', label: 'مراسل تركيا' },
]

function CompanyTab({ currentUserRole }: { currentUserRole: 'ADMIN' | 'ACCOUNTANT' }) {
  const [profile, setProfile] = useState<CompanyProfile | null>(null)
  const [nameAr, setNameAr] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void api.get<CompanyProfile>('/settings/company').then((p) => { setProfile(p); setNameAr(p.name_ar) })
  }, [])

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      const updated = await api.put<CompanyProfile>('/settings/company', { name_ar: nameAr })
      setProfile(updated)
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر الحفظ')
    } finally {
      setBusy(false)
    }
  }

  if (!profile) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <form onSubmit={save} style={{ maxWidth: 420 }}>
      <div className="field" style={{ marginBottom: 12 }}>
        <label className="field-label" htmlFor="settings-company-name">اسم الشركة</label>
        <input
          id="settings-company-name" value={nameAr} onChange={(e) => setNameAr(e.target.value)}
          disabled={currentUserRole !== 'ADMIN'} required
        />
      </div>
      {currentUserRole !== 'ADMIN' && <p className="text-muted" style={{ fontSize: 12.5 }}>عرض فقط — التعديل بصلاحية المدير</p>}
      {error && <div className="alert alert-critical" style={{ marginBottom: 12 }}>{error}</div>}
      {saved && <div className="alert alert-info" style={{ marginBottom: 12 }}>تم الحفظ</div>}
      {currentUserRole === 'ADMIN' && (
        <button type="submit" className="btn btn-primary" disabled={busy}>حفظ</button>
      )}
    </form>
  )
}

function CreateUserForm({ onCreated }: { onCreated: () => void }) {
  const [username, setUsername] = useState('')
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState<'ADMIN' | 'ACCOUNTANT'>('ACCOUNTANT')
  const [initialPassword, setInitialPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post('/users', { username, full_name: fullName, role, initial_password: initialPassword })
      setUsername(''); setFullName(''); setInitialPassword(''); setRole('ACCOUNTANT')
      onCreated()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر إنشاء المستخدم')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="op-row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 16, alignItems: 'flex-end' }}>
      <div className="field"><label className="field-label" htmlFor="su-username">اسم المستخدم</label><input id="su-username" value={username} onChange={(e) => setUsername(e.target.value)} required /></div>
      <div className="field"><label className="field-label" htmlFor="su-fullname">الاسم الكامل</label><input id="su-fullname" value={fullName} onChange={(e) => setFullName(e.target.value)} required /></div>
      <div className="field">
        <label className="field-label" htmlFor="su-role">الدور</label>
        <select id="su-role" value={role} onChange={(e) => setRole(e.target.value as 'ADMIN' | 'ACCOUNTANT')}>
          <option value="ACCOUNTANT">محاسب</option>
          <option value="ADMIN">مدير</option>
        </select>
      </div>
      <div className="field"><label className="field-label" htmlFor="su-pass">كلمة مرور مبدئية</label><input id="su-pass" type="password" value={initialPassword} onChange={(e) => setInitialPassword(e.target.value)} minLength={10} required /></div>
      <button type="submit" className="btn btn-primary" disabled={busy}>+ مستخدم جديد</button>
      {error && <div className="alert alert-critical" style={{ width: '100%' }}>{error}</div>}
    </form>
  )
}

function UsersTab() {
  const [rows, setRows] = useState<UserListRow[] | null>(null)

  async function reload() {
    const data = await api.get<UserListRow[]>('/users')
    setRows(data)
  }

  useEffect(() => { void reload() }, [])

  return (
    <>
      <CreateUserForm onCreated={() => void reload()} />
      {!rows ? <p className="text-muted">...جارٍ التحميل</p> : (
        <table className="data-table">
          <thead><tr><th>اسم المستخدم</th><th>الاسم الكامل</th><th>الدور</th><th>الحالة</th><th>تغيير كلمة المرور</th></tr></thead>
          <tbody>
            {rows.map((u) => (
              <tr key={u.id}>
                <td className="num">{u.username}</td>
                <td>{u.full_name}</td>
                <td>{u.role === 'ADMIN' ? 'مدير' : 'محاسب'}</td>
                <td><span className={`badge ${u.is_active ? 'badge-status-posted' : 'badge-status-reversed'}`}>{u.is_active ? 'نشط' : 'معطَّل'}</span></td>
                <td className="text-muted">{u.must_change_password ? 'مطلوب' : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}

function CreatePartnerForm({ onCreated }: { onCreated: () => void }) {
  const [code, setCode] = useState('')
  const [nameAr, setNameAr] = useState('')
  const [country, setCountry] = useState('')
  const [phone, setPhone] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post('/partners', { code, name_ar: nameAr, country, contact_phone: phone || undefined })
      setCode(''); setNameAr(''); setCountry(''); setPhone('')
      onCreated()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر إنشاء الشريك')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="op-row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 16, alignItems: 'flex-end' }}>
      <div className="field"><label className="field-label" htmlFor="sp-code">الكود</label><input id="sp-code" value={code} onChange={(e) => setCode(e.target.value)} required /></div>
      <div className="field"><label className="field-label" htmlFor="sp-name">الاسم</label><input id="sp-name" value={nameAr} onChange={(e) => setNameAr(e.target.value)} required /></div>
      <div className="field"><label className="field-label" htmlFor="sp-country">الدولة</label><input id="sp-country" value={country} onChange={(e) => setCountry(e.target.value)} required /></div>
      <div className="field"><label className="field-label" htmlFor="sp-phone">هاتف (اختياري)</label><input id="sp-phone" value={phone} onChange={(e) => setPhone(e.target.value)} /></div>
      <button type="submit" className="btn btn-primary" disabled={busy}>+ شريك جديد</button>
      {error && <div className="alert alert-critical" style={{ width: '100%' }}>{error}</div>}
    </form>
  )
}

function CreatePartnerAccountForm({ partnerId, onCreated }: { partnerId: number; onCreated: () => void }) {
  const { currencies, locationsForCurrency } = useReferenceData()
  const [parentCode, setParentCode] = useState('1320')
  const [currency, setCurrency] = useState('')
  const [location, setLocation] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const locations = locationsForCurrency(currency)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post(`/partners/${partnerId}/accounts`, { parent_code: parentCode, currency_code: currency, location_code: location })
      onCreated()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر إنشاء الحساب')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="op-row" style={{ flexWrap: 'wrap', gap: 8, margin: '8px 0', alignItems: 'flex-end' }}>
      <div className="field">
        <label className="field-label">النوع</label>
        <select value={parentCode} onChange={(e) => setParentCode(e.target.value)}>
          {PARTNER_ACCOUNT_PARENTS.map((p) => <option key={p.code} value={p.code}>{p.label}</option>)}
        </select>
      </div>
      <div className="field">
        <label className="field-label">العملة</label>
        <select value={currency} onChange={(e) => { setCurrency(e.target.value); setLocation('') }} required>
          <option value="">اختر...</option>
          {currencies.map((c) => <option key={c.code} value={c.code}>{c.name_ar}</option>)}
        </select>
      </div>
      <div className="field">
        <label className="field-label">الموقع</label>
        <select value={location} onChange={(e) => setLocation(e.target.value)} required disabled={!currency}>
          <option value="">اختر...</option>
          {locations.map((l) => <option key={l.code} value={l.code}>{l.name_ar}</option>)}
        </select>
      </div>
      <button type="submit" className="btn btn-secondary btn-sm" disabled={busy || !currency || !location}>+ حساب</button>
      {error && <div className="alert alert-critical" style={{ width: '100%' }}>{error}</div>}
    </form>
  )
}

function PartnerAccountsRow({ partner }: { partner: PartnerRow }) {
  const [expanded, setExpanded] = useState(false)
  const [accounts, setAccounts] = useState<AccountOut[] | null>(null)

  async function reload() {
    const data = await api.get<AccountOut[]>(`/partners/${partner.id}/accounts`)
    setAccounts(data)
  }

  useEffect(() => { if (expanded) void reload() }, [expanded])

  return (
    <>
      <tr className="acc-lot-row" onClick={() => setExpanded((v) => !v)}>
        <td className="num text-muted">{partner.code}</td>
        <td>{partner.name_ar}</td>
        <td>{partner.country}</td>
        <td className="num">{partner.contact_phone ?? '—'}</td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={4} style={{ background: 'var(--sky-50)', padding: 'var(--space-3)' }}>
            {!accounts ? <p className="text-muted">...جارٍ التحميل</p> : (
              <>
                <table className="data-table" style={{ marginBottom: 4 }}>
                  <thead><tr><th>الكود</th><th>الاسم</th><th>العملة</th></tr></thead>
                  <tbody>
                    {accounts.map((a) => (
                      <tr key={a.id}><td className="num text-muted">{a.code}</td><td>{a.name_ar}</td><td>{a.currency_code}</td></tr>
                    ))}
                    {accounts.length === 0 && <tr><td colSpan={3} className="text-muted">لا حسابات مالية لهذا الشريك بعد</td></tr>}
                  </tbody>
                </table>
                <CreatePartnerAccountForm partnerId={partner.id} onCreated={() => void reload()} />
              </>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

function PartnersTab() {
  const [rows, setRows] = useState<PartnerRow[] | null>(null)

  async function reload() {
    const data = await api.get<PartnerRow[]>('/partners')
    setRows(data)
  }

  useEffect(() => { void reload() }, [])

  return (
    <>
      <CreatePartnerForm onCreated={() => void reload()} />
      {!rows ? <p className="text-muted">...جارٍ التحميل</p> : (
        <table className="data-table">
          <thead><tr><th>الكود</th><th>الاسم</th><th>الدولة</th><th>الهاتف</th></tr></thead>
          <tbody>
            {rows.map((p) => <PartnerAccountsRow key={p.id} partner={p} />)}
            {rows.length === 0 && <tr><td colSpan={4} className="text-muted">لا شركاء مسجَّلين بعد</td></tr>}
          </tbody>
        </table>
      )}
    </>
  )
}

function CreateBankAccountForm({ onCreated }: { onCreated: () => void }) {
  const { currencies, locationsForCurrency } = useReferenceData()
  const [currency, setCurrency] = useState('')
  const [location, setLocation] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const locations = locationsForCurrency(currency)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post('/settings/bank-accounts', { currency_code: currency, location_code: location })
      onCreated()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر إنشاء الحساب')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="op-row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 16, alignItems: 'flex-end' }}>
      <div className="field">
        <label className="field-label">العملة</label>
        <select value={currency} onChange={(e) => { setCurrency(e.target.value); setLocation('') }} required>
          <option value="">اختر...</option>
          {currencies.map((c) => <option key={c.code} value={c.code}>{c.name_ar}</option>)}
        </select>
      </div>
      <div className="field">
        <label className="field-label">الموقع</label>
        <select value={location} onChange={(e) => setLocation(e.target.value)} required disabled={!currency}>
          <option value="">اختر...</option>
          {locations.map((l) => <option key={l.code} value={l.code}>{l.name_ar}</option>)}
        </select>
      </div>
      <button type="submit" className="btn btn-primary" disabled={busy || !currency || !location}>+ حساب بنكي جديد</button>
      {error && <div className="alert alert-critical" style={{ width: '100%' }}>{error}</div>}
    </form>
  )
}

function BankAccountsTab() {
  const [rows, setRows] = useState<AccountOut[] | null>(null)

  async function reload() {
    const data = await api.get<AccountOut[]>('/settings/bank-accounts')
    setRows(data)
  }

  useEffect(() => { void reload() }, [])

  return (
    <>
      <CreateBankAccountForm onCreated={() => void reload()} />
      {!rows ? <p className="text-muted">...جارٍ التحميل</p> : (
        <table className="data-table">
          <thead><tr><th>الكود</th><th>الاسم</th><th>العملة</th></tr></thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id}><td className="num text-muted">{a.code}</td><td>{a.name_ar}</td><td>{a.currency_code}</td></tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={3} className="text-muted">لا حسابات بنكية مسجَّلة بعد</td></tr>}
          </tbody>
        </table>
      )}
    </>
  )
}

export function SettingsScreen({ currentUserRole }: { currentUserRole: 'ADMIN' | 'ACCOUNTANT' }) {
  const [tab, setTab] = useState<SettingsTab>('company')

  return (
    <div className="journal-screen">
      <h2 className="screen-title" style={{ marginBottom: 16 }}>الإعدادات</h2>
      <div className="op-tabs" style={{ marginBottom: 12 }}>
        {TABS.map((t) => (
          <button key={t.id} type="button" className={`op-tab${tab === t.id ? ' is-active' : ''}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="card" style={{ overflowX: 'auto' }}>
        {tab === 'company' && <CompanyTab currentUserRole={currentUserRole} />}
        {tab === 'users' && (currentUserRole === 'ADMIN' ? <UsersTab /> : <p className="text-muted">هذا القسم بصلاحية المدير فقط</p>)}
        {tab === 'partners' && (currentUserRole === 'ADMIN' ? <PartnersTab /> : <p className="text-muted">هذا القسم بصلاحية المدير فقط</p>)}
        {tab === 'bank-accounts' && (currentUserRole === 'ADMIN' ? <BankAccountsTab /> : <p className="text-muted">هذا القسم بصلاحية المدير فقط</p>)}
        {tab === 'opening-balances' && (currentUserRole === 'ADMIN' ? <OpeningBalancesTab /> : <p className="text-muted">هذا القسم بصلاحية المدير فقط</p>)}
        {tab === 'periods' && (currentUserRole === 'ADMIN' ? <PeriodsTab /> : <p className="text-muted">هذا القسم بصلاحية المدير فقط</p>)}
        {tab === 'audit-log' && (currentUserRole === 'ADMIN' ? <AuditLogTab /> : <p className="text-muted">هذا القسم بصلاحية المدير فقط</p>)}
      </div>
    </div>
  )
}
