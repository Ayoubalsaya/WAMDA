import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { PortalInviteVerifyResponse } from '../api/types'
import { LogoMark } from '../components/LogoMark'
import './PortalLoginScreen.css'

interface PortalAcceptInviteScreenProps {
  token: string
}

type Phase = 'checking' | 'invalid' | 'form' | 'done'

function goToLogin() {
  // يزيل #invite=... من الرابط ويعيد تحميل الصفحة — PortalApp يعرض شاشة
  // الدخول العادية بمجرد غياب الرمز من hash الصفحة.
  window.location.hash = ''
  window.location.reload()
}

export function PortalAcceptInviteScreen({ token }: PortalAcceptInviteScreenProps) {
  const [phase, setPhase] = useState<Phase>('checking')
  const [firstName, setFirstName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .post<PortalInviteVerifyResponse>('/portal/invite/verify', { token })
      .then((res) => {
        if (cancelled) return
        setFirstName(res.client_first_name)
        setPhase('form')
      })
      .catch(() => {
        if (!cancelled) setPhase('invalid')
      })
    return () => {
      cancelled = true
    }
  }, [token])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (password.length < 10) {
      setError('كلمة المرور يجب أن تكون ١٠ أحرف على الأقل')
      return
    }
    if (password !== confirm) {
      setError('كلمتا المرور غير متطابقتين')
      return
    }
    setBusy(true)
    try {
      await api.post('/portal/invite/accept', { token, password })
      setPhase('done')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر تعيين كلمة المرور')
    } finally {
      setBusy(false)
    }
  }

  if (phase === 'checking') {
    return <div className="app-loading">...جارٍ التحقق من رابط الدعوة</div>
  }

  if (phase === 'invalid') {
    return (
      <div className="portal-login-screen">
        <div className="portal-login-brand">
          <div className="portal-login-logo">
            <LogoMark size={40} />
          </div>
          <h1 className="portal-login-name">ومضة</h1>
        </div>
        <div className="alert alert-critical">رابط الدعوة غير صالح أو منتهٍ — اطلب من إدارة الحساب رابطاً جديداً.</div>
        <button type="button" className="btn btn-primary btn-lg" style={{ width: '100%' }} onClick={goToLogin}>
          الذهاب لتسجيل الدخول
        </button>
      </div>
    )
  }

  if (phase === 'done') {
    return (
      <div className="portal-login-screen">
        <div className="portal-login-brand">
          <div className="portal-login-logo">
            <LogoMark size={40} />
          </div>
          <h1 className="portal-login-name">ومضة</h1>
          <p className="portal-login-tagline">تم تعيين كلمة مرورك بنجاح</p>
        </div>
        <button type="button" className="btn btn-primary btn-lg" style={{ width: '100%' }} onClick={goToLogin}>
          الدخول للبوابة الآن
        </button>
      </div>
    )
  }

  return (
    <div className="portal-login-screen">
      <div className="portal-login-brand">
        <div className="portal-login-logo">
          <LogoMark size={40} />
        </div>
        <h1 className="portal-login-name">ومضة</h1>
        <p className="portal-login-tagline">أهلاً {firstName} — عيّن كلمة مرورك للبوابة</p>
      </div>
      <form className="portal-login-form" onSubmit={submit}>
        <div className="field">
          <label className="field-label" htmlFor="invite-password">
            كلمة المرور الجديدة (١٠ أحرف على الأقل)
          </label>
          <input
            id="invite-password" type="password" value={password}
            onChange={(e) => setPassword(e.target.value)} required autoFocus
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="invite-confirm">تأكيد كلمة المرور</label>
          <input
            id="invite-confirm" type="password" value={confirm}
            onChange={(e) => setConfirm(e.target.value)} required
          />
        </div>
        {error && <div className="alert alert-critical">{error}</div>}
        <button type="submit" className="btn btn-primary btn-lg" disabled={busy} style={{ width: '100%' }}>
          حفظ كلمة المرور
        </button>
      </form>
    </div>
  )
}
