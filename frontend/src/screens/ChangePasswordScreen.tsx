import { useState } from 'react'
import { api, ApiError } from '../api/client'
import { LogoMark } from '../components/LogoMark'
import './LoginScreen.css'

interface ChangePasswordScreenProps {
  onDone: () => Promise<void>
  onLogout: () => Promise<void>
}

export function ChangePasswordScreen({ onDone, onLogout }: ChangePasswordScreenProps) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (newPassword.length < 10) {
      setError('كلمة المرور الجديدة يجب أن تكون ١٠ أحرف على الأقل')
      return
    }
    if (newPassword !== confirm) {
      setError('كلمتا المرور الجديدتان غير متطابقتين')
      return
    }
    setBusy(true)
    try {
      await api.post('/auth/change-password', { current_password: currentPassword, new_password: newPassword })
      await onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر تغيير كلمة المرور')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-screen">
      <div className="login-brand">
        <div className="login-logo-mark" aria-hidden="true"><LogoMark /></div>
        <h1 className="login-brand-name">ومضة</h1>
        <p className="login-brand-en">WAMDA FINANCIAL SYSTEM</p>
        <p className="login-brand-tagline">هذا أول دخول لك — يجب تعيين كلمة مرور جديدة قبل المتابعة</p>
      </div>
      <div className="login-form-side">
        <form className="login-form" onSubmit={submit}>
          <h2 className="screen-title">تغيير كلمة المرور</h2>
          <div className="field">
            <label className="field-label" htmlFor="cp-current">كلمة المرور الحالية</label>
            <input id="cp-current" type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required autoFocus />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="cp-new">كلمة المرور الجديدة (١٠ أحرف على الأقل)</label>
            <input id="cp-new" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="cp-confirm">تأكيد كلمة المرور الجديدة</label>
            <input id="cp-confirm" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
          </div>
          {error && <div className="alert alert-critical">{error}</div>}
          <button type="submit" className="btn btn-primary btn-lg" disabled={busy} style={{ width: '100%' }}>
            حفظ كلمة المرور والمتابعة
          </button>
          <button type="button" className="btn-text" onClick={() => void onLogout()}>خروج</button>
        </form>
      </div>
    </div>
  )
}
