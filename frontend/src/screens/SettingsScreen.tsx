import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { CompanyProfile, PartnerRow, UserListRow } from '../api/types'
import './SettingsScreen.css'

type SettingsTab = 'company' | 'users' | 'partners'

const TABS: { id: SettingsTab; label: string }[] = [
  { id: 'company', label: 'ملف الشركة' },
  { id: 'users', label: 'المستخدمون' },
  { id: 'partners', label: 'الشركاء' },
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
            {rows.map((p) => (
              <tr key={p.id}>
                <td className="num text-muted">{p.code}</td>
                <td>{p.name_ar}</td>
                <td>{p.country}</td>
                <td className="num">{p.contact_phone ?? '—'}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={4} className="text-muted">لا شركاء مسجَّلين بعد</td></tr>}
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
      </div>
    </div>
  )
}
