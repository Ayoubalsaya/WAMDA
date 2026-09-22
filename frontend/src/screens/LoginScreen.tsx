import { useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { api, ApiError } from '../api/client'
import type { LoginResponse } from '../api/types'
import { LogoMark } from '../components/LogoMark'
import './LoginScreen.css'

interface LoginScreenProps {
  login: (username: string, password: string, totpCode?: string, totpSecretSetup?: string) => Promise<LoginResponse>
}

type Step = 'credentials' | 'totp_required' | 'totp_setup_required' | 'forgot'

// د: "نسيت كلمة المرور" كانت رابطاً href="#" بلا أي سلوك — نفس صنف علّة
// الجرس (عنصر يَعِد بلا معالج). تستخدم تدفّق §٩ الحقيقي القائم أصلاً
// (POST /auth/recover/start ثم /complete) — بلا منطق جديد في الخادم.
function ForgotPasswordForm({ onDone }: { onDone: () => void }) {
  const [stage, setStage] = useState<'start' | 'answer' | 'no-question'>('start')
  const [username, setUsername] = useState('')
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  async function submitUsername(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await api.post<{ security_question: string | null }>('/auth/recover/start', { username })
      if (res.security_question) {
        setQuestion(res.security_question)
        setStage('answer')
      } else {
        setStage('no-question')
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر بدء الاستعادة')
    } finally {
      setBusy(false)
    }
  }

  async function submitReset(e: React.FormEvent) {
    e.preventDefault()
    if (newPassword !== confirmPassword) {
      setError('كلمتا المرور غير متطابقتين')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.post('/auth/recover/complete', { username, security_answer: answer, new_password: newPassword })
      setDone(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّرت استعادة كلمة المرور')
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <div className="login-form">
        <h2 className="screen-title">تم بنجاح</h2>
        <div className="alert alert-info">تم تغيير كلمة المرور — يمكنك تسجيل الدخول بها الآن.</div>
        <button type="button" className="btn btn-primary btn-lg" style={{ width: '100%' }} onClick={onDone}>
          العودة لتسجيل الدخول
        </button>
      </div>
    )
  }

  if (stage === 'no-question') {
    return (
      <div className="login-form">
        <h2 className="screen-title">تعذّرت الاستعادة</h2>
        <div className="alert alert-warning">
          لا سؤال تحقق مسجَّل لهذا الحساب — تواصل مع المدير لإعادة تعيين كلمة المرور يدوياً.
        </div>
        <button type="button" className="btn btn-secondary btn-lg" style={{ width: '100%' }} onClick={onDone}>
          رجوع لتسجيل الدخول
        </button>
      </div>
    )
  }

  if (stage === 'answer') {
    return (
      <form className="login-form" onSubmit={submitReset}>
        <h2 className="screen-title">استعادة كلمة المرور</h2>
        <div className="field">
          <label className="field-label">{question}</label>
          <input value={answer} onChange={(e) => setAnswer(e.target.value)} required autoFocus />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="new-password">كلمة مرور جديدة (١٠ أحرف على الأقل)</label>
          <input id="new-password" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} minLength={10} required />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="confirm-password">تأكيد كلمة المرور</label>
          <input id="confirm-password" type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} minLength={10} required />
        </div>
        {error && <div className="alert alert-critical">{error}</div>}
        <button type="submit" className="btn btn-primary btn-lg" disabled={busy} style={{ width: '100%' }}>
          تعيين كلمة المرور
        </button>
        <button type="button" className="btn-text login-forgot" onClick={onDone}>رجوع لتسجيل الدخول</button>
      </form>
    )
  }

  return (
    <form className="login-form" onSubmit={submitUsername}>
      <h2 className="screen-title">نسيت كلمة المرور</h2>
      <div className="field">
        <label className="field-label" htmlFor="forgot-username">اسم المستخدم</label>
        <input id="forgot-username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
      </div>
      {error && <div className="alert alert-critical">{error}</div>}
      <button type="submit" className="btn btn-primary btn-lg" disabled={busy || !username.trim()} style={{ width: '100%' }}>
        متابعة
      </button>
      <button type="button" className="btn-text login-forgot" onClick={onDone}>رجوع لتسجيل الدخول</button>
    </form>
  )
}

export function LoginScreen({ login }: LoginScreenProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [candidateSecret, setCandidateSecret] = useState<string | null>(null)
  const [provisioningUri, setProvisioningUri] = useState<string | null>(null)
  const [step, setStep] = useState<Step>('credentials')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  const totpValid = /^\d{6}$/.test(totpCode)

  async function submitCredentials(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const res = await login(username, password)
      if (res.status === 'totp_required') setStep('totp_required')
      else if (res.status === 'totp_setup_required') {
        setCandidateSecret(res.totp_secret ?? null)
        setProvisioningUri(res.provisioning_uri ?? null)
        setStep('totp_setup_required')
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر تسجيل الدخول')
    } finally {
      setBusy(false)
    }
  }

  async function submitTotp(e: React.FormEvent) {
    e.preventDefault()
    if (!totpValid) return // لا محاولة فعلية قبل اكتمال ٦ أرقام — لا رسالة خطأ زائفة
    setError(null)
    setBusy(true)
    try {
      if (step === 'totp_setup_required') {
        await login(username, password, totpCode, candidateSecret ?? undefined)
      } else {
        await login(username, password, totpCode)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'رمز التحقق غير صحيح')
    } finally {
      setBusy(false)
    }
  }

  async function copySecret() {
    if (!candidateSecret) return
    await navigator.clipboard.writeText(candidateSecret)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="login-screen">
      <div className="login-brand">
        <div className="login-logo-mark" aria-hidden="true"><LogoMark /></div>
        <h1 className="login-brand-name">ومضة</h1>
        <p className="login-brand-en">WAMDA FINANCIAL SYSTEM</p>
        <p className="login-brand-tagline">نظام إدارة تحويلات وصرافة — ليبيا · تركيا · الصين</p>
      </div>

      <div className="login-form-side">
        {step === 'credentials' && (
          <form className="login-form" onSubmit={submitCredentials}>
            <h2 className="screen-title">تسجيل الدخول</h2>
            <div className="field">
              <label className="field-label" htmlFor="username">اسم المستخدم</label>
              <input id="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="password">كلمة المرور</label>
              <input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            {error && <div className="alert alert-critical">{error}</div>}
            <button type="submit" className="btn btn-primary btn-lg" disabled={busy} style={{ width: '100%' }}>
              دخول
            </button>
            <button type="button" className="btn-text login-forgot" onClick={() => setStep('forgot')}>
              نسيت كلمة المرور
            </button>
          </form>
        )}

        {step === 'forgot' && <ForgotPasswordForm onDone={() => setStep('credentials')} />}

        {(step === 'totp_required' || step === 'totp_setup_required') && (
          <form className="login-form" onSubmit={submitTotp}>
            <h2 className="screen-title">رمز التحقق</h2>
            {step === 'totp_setup_required' && (
              <div className="alert alert-info totp-setup-block">
                <p>هذا أول تسجيل دخول — امسح رمز QR بتطبيق المصادقة (Google Authenticator ونحوه).</p>
                {provisioningUri && (
                  <div className="qr-wrap">
                    <QRCodeSVG value={provisioningUri} size={176} marginSize={2} level="M" />
                  </div>
                )}
                {candidateSecret && (
                  <div className="totp-secret-fallback">
                    <span className="field-label">تعذّر المسح؟ أدخل السرّ يدوياً:</span>
                    <div className="totp-secret-row">
                      <code className="num totp-secret-code">{candidateSecret}</code>
                      <button type="button" className="btn btn-secondary btn-sm" onClick={() => void copySecret()}>
                        {copied ? 'نُسخ ✓' : 'نسخ السرّ'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
            <div className="field">
              <label className="field-label" htmlFor="totp">رمز من ٦ أرقام</label>
              <input
                id="totp" className="num" inputMode="numeric" maxLength={6} value={totpCode}
                onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                required autoFocus
              />
            </div>
            {error && <div className="alert alert-critical">{error}</div>}
            <button type="submit" className="btn btn-primary btn-lg" disabled={busy || !totpValid} style={{ width: '100%' }}>
              تأكيد
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
