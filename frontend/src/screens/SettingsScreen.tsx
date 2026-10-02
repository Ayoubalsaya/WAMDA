import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AccountOut, CompanyProfile, PartnerRow, UserListRow } from '../api/types'
import { useReferenceData } from '../hooks/useReferenceData'
import { SegmentedTabs } from '../components/SegmentedTabs'
import { AuditLogTab } from './settings/AuditLogTab'
import { CurrenciesTab } from './settings/CurrenciesTab'
import { LocationsTab } from './settings/LocationsTab'
import { OpeningBalancesTab } from './settings/OpeningBalancesTab'
import { PeriodsTab } from './settings/PeriodsTab'
import './SettingsScreen.css'
import { useFormErrors } from '../hooks/useFormErrors'
import { SecurityTab } from './settings/SecurityTab'

type SettingsTab = 'security' | 'company' | 'users' | 'partners' | 'bank-accounts' | 'currencies' | 'locations' | 'opening-balances' | 'periods' | 'audit-log'

const TABS: { id: SettingsTab; label: string }[] = [
  { id: 'company', label: 'ملف الشركة' },
  { id: 'security', label: 'الأمان' },
  { id: 'users', label: 'المستخدمون' },
  { id: 'partners', label: 'الشركاء' },
  { id: 'bank-accounts', label: 'الحسابات البنكية' },
  { id: 'currencies', label: 'العملات' },
  { id: 'locations', label: 'المواقع' },
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
  const { ref: formRef, error, setError, report, portals } = useFormErrors({ name_ar: 'اسم الشركة' })

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
      report(err, 'تعذّر الحفظ')
    } finally {
      setBusy(false)
    }
  }

  if (!profile) return <p className="text-muted">...جارٍ التحميل</p>
  return (
    <form ref={formRef} onSubmit={save} style={{ maxWidth: 420 }}>
      <div className="field" style={{ marginBottom: 12 }}>
        <label className="field-label" htmlFor="settings-company-name">اسم الشركة</label>
        <input
          id="settings-company-name" value={nameAr} onChange={(e) => setNameAr(e.target.value)}
          disabled={currentUserRole !== 'ADMIN'} required
        />
      </div>
      {currentUserRole !== 'ADMIN' && <p className="text-muted" style={{ fontSize: 'var(--fs-xs)' }}>عرض فقط — التعديل بصلاحية المدير</p>}
      {error && <div className="alert alert-critical" style={{ marginBottom: 12 }}>{error}</div>}
      {portals}
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
  const { ref: formRef, error, setError, report, portals } = useFormErrors({ username: 'اسم المستخدم', full_name: 'الاسم الكامل', role: 'الدور', initial_password: 'كلمة مرور مبدئية' })

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post('/users', { username, full_name: fullName, role, initial_password: initialPassword })
      setUsername(''); setFullName(''); setInitialPassword(''); setRole('ACCOUNTANT')
      onCreated()
    } catch (err) {
      report(err, 'تعذّر إنشاء المستخدم')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form ref={formRef} onSubmit={submit} className="op-row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 16, alignItems: 'flex-end' }}>
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
      {portals}
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
  const { ref: formRef, error, setError, report, portals } = useFormErrors({ code: 'الكود', name_ar: 'الاسم', country: 'الدولة', contact_phone: 'هاتف' })

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post('/partners', { code, name_ar: nameAr, country, contact_phone: phone || undefined })
      setCode(''); setNameAr(''); setCountry(''); setPhone('')
      onCreated()
    } catch (err) {
      report(err, 'تعذّر إنشاء الشريك')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form ref={formRef} onSubmit={submit} className="op-row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 16, alignItems: 'flex-end' }}>
      <div className="field"><label className="field-label" htmlFor="sp-code">الكود</label><input id="sp-code" value={code} onChange={(e) => setCode(e.target.value)} required /></div>
      <div className="field"><label className="field-label" htmlFor="sp-name">الاسم</label><input id="sp-name" value={nameAr} onChange={(e) => setNameAr(e.target.value)} required /></div>
      <div className="field"><label className="field-label" htmlFor="sp-country">الدولة</label><input id="sp-country" value={country} onChange={(e) => setCountry(e.target.value)} required /></div>
      <div className="field"><label className="field-label" htmlFor="sp-phone">هاتف (اختياري)</label><input id="sp-phone" value={phone} onChange={(e) => setPhone(e.target.value)} /></div>
      <button type="submit" className="btn btn-primary" disabled={busy}>+ شريك جديد</button>
      {error && <div className="alert alert-critical" style={{ width: '100%' }}>{error}</div>}
      {portals}
    </form>
  )
}

function CreatePartnerAccountForm({ partnerId, onCreated }: { partnerId: number; onCreated: () => void }) {
  // ملاحظة (٢٠٢٦-٠٩-٢٥، اكتُشفت أثناء تحقق العملة الرابعة حياً):
  // `locationsForCurrency` يُقيَّد بـ`client_currency_locations` — قائمة
  // بيضاء لحسابات العملاء حصراً (§٢-٢). حساب مراسل/بنك مملوك (طرف الشركة)
  // لا يخضع لهذا القيد إطلاقاً — لا تحقق مطابق في accounts_repo.create_bank_account
  // ولا في مسار إنشاء حساب الشريك، فاستخدام القائمة المُصفّاة هنا كان يمنع
  // إنشاء أول حساب مراسل بعملة جديدة (لا صفوف whitelist لها بعد أبداً).
  const { currencies, locations } = useReferenceData()
  const [parentCode, setParentCode] = useState('1320')
  const [currency, setCurrency] = useState('')
  const [location, setLocation] = useState('')
  const [busy, setBusy] = useState(false)
  const { ref: formRef, error, setError, report, portals } = useFormErrors({ parent_code: 'النوع', currency_code: 'العملة', location_code: 'الموقع' })

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post(`/partners/${partnerId}/accounts`, { parent_code: parentCode, currency_code: currency, location_code: location })
      onCreated()
    } catch (err) {
      report(err, 'تعذّر إنشاء الحساب')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form ref={formRef} onSubmit={submit} className="op-row" style={{ flexWrap: 'wrap', gap: 8, margin: '8px 0', alignItems: 'flex-end' }}>
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
      {portals}
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
  // نفس ملاحظة CreatePartnerAccountForm أعلاه — حساب بنكي مملوك ليس حساب
  // عميل، فلا يُقيَّد بقائمة client_currency_locations البيضاء.
  const { currencies, locations } = useReferenceData()
  const [currency, setCurrency] = useState('')
  const [location, setLocation] = useState('')
  const [busy, setBusy] = useState(false)
  const { ref: formRef, error, setError, report, portals } = useFormErrors({ currency_code: 'العملة', location_code: 'الموقع' })

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post('/settings/bank-accounts', { currency_code: currency, location_code: location })
      onCreated()
    } catch (err) {
      report(err, 'تعذّر إنشاء الحساب')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form ref={formRef} onSubmit={submit} className="op-row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 16, alignItems: 'flex-end' }}>
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
      {portals}
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
      <div style={{ marginBottom: 12 }}>
        <SegmentedTabs variant="dock" ariaLabel="أقسام الإعدادات" value={tab} onChange={setTab} items={TABS} />
      </div>
      <div className="card" style={{ overflowX: 'auto' }}>
        {tab === 'company' && <CompanyTab currentUserRole={currentUserRole} />}
        {tab === 'security' && <SecurityTab />}
        {tab === 'users' && (currentUserRole === 'ADMIN' ? <UsersTab /> : <p className="text-muted">هذا القسم بصلاحية المدير فقط</p>)}
        {tab === 'partners' && (currentUserRole === 'ADMIN' ? <PartnersTab /> : <p className="text-muted">هذا القسم بصلاحية المدير فقط</p>)}
        {tab === 'bank-accounts' && (currentUserRole === 'ADMIN' ? <BankAccountsTab /> : <p className="text-muted">هذا القسم بصلاحية المدير فقط</p>)}
        {tab === 'currencies' && (currentUserRole === 'ADMIN' ? <CurrenciesTab /> : <p className="text-muted">هذا القسم بصلاحية المدير فقط</p>)}
        {tab === 'locations' && (currentUserRole === 'ADMIN' ? <LocationsTab /> : <p className="text-muted">هذا القسم بصلاحية المدير فقط</p>)}
        {tab === 'opening-balances' && (currentUserRole === 'ADMIN' ? <OpeningBalancesTab /> : <p className="text-muted">هذا القسم بصلاحية المدير فقط</p>)}
        {tab === 'periods' && (currentUserRole === 'ADMIN' ? <PeriodsTab /> : <p className="text-muted">هذا القسم بصلاحية المدير فقط</p>)}
        {tab === 'audit-log' && (currentUserRole === 'ADMIN' ? <AuditLogTab /> : <p className="text-muted">هذا القسم بصلاحية المدير فقط</p>)}
      </div>
    </div>
  )
}
