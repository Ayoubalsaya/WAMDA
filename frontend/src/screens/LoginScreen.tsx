import { useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { ApiError } from '../api/client'
import type { LoginResponse } from '../api/types'
import { LogoMark } from '../components/LogoMark'
import { BackupCodesPanel } from '../components/BackupCodesPanel'
import './LoginScreen.css'

interface LoginScreenProps {
  login: (username: string, password: string, totpCode?: string, totpSecretSetup?: string, backupCode?: string) => Promise<LoginResponse>
  refresh: () => Promise<void>
}

type Step = 'credentials' | 'totp_required' | 'totp_setup_required'

export function LoginScreen({ login, refresh }: LoginScreenProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [candidateSecret, setCandidateSecret] = useState<string | null>(null)
  const [provisioningUri, setProvisioningUri] = useState<string | null>(null)
  const [step, setStep] = useState<Step>('credentials')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const [useBackup, setUseBackup] = useState(false)
  const [backupCode, setBackupCode] = useState('')
  const [issuedCodes, setIssuedCodes] = useState<string[] | null>(null)

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
    if (useBackup && step === 'totp_required') {
      if (!backupCode.trim()) return
      setError(null)
      setBusy(true)
      try {
        await login(username, password, undefined, undefined, backupCode.trim())
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'الرمز الاحتياطي غير صحيح')
      } finally {
        setBusy(false)
      }
      return
    }
    if (!totpValid) return // لا محاولة فعلية قبل اكتمال ٦ أرقام — لا رسالة خطأ زائفة
    setError(null)
    setBusy(true)
    try {
      if (step === 'totp_setup_required') {
        const res = await login(username, password, totpCode, candidateSecret ?? undefined)
        // أول إعداد للمصادقة: تُعرض الرموز الاحتياطية **إلزامياً** قبل المتابعة (لا تُعرض ثانية)
        if (res.backup_codes) setIssuedCodes(res.backup_codes)
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

  if (issuedCodes) {
    return (
      <div className="login-screen">
        <div className="login-form-side" style={{ gridColumn: '1 / -1' }}>
          <div className="login-form" style={{ maxWidth: 520 }}>
            <BackupCodesPanel
              codes={issuedCodes} title="الرموز الاحتياطية — احفظها الآن" continueLabel="متابعة إلى النظام"
              onAcknowledged={() => { setIssuedCodes(null); void refresh() }}
            />
          </div>
        </div>
      </div>
    )
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
            <p className="login-forgot">نسيت كلمة المرور؟ اطلب من المدير إعادة تعيينها.</p>
          </form>
        )}

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
            {useBackup && step === 'totp_required' ? (
              <div className="field">
                <label className="field-label" htmlFor="backup-code">رمز احتياطي (يعمل مرة واحدة)</label>
                <input
                  id="backup-code" className="num" value={backupCode} placeholder="XXXXX-XXXXX" autoComplete="off"
                  onChange={(e) => setBackupCode(e.target.value.toUpperCase().slice(0, 12))} required autoFocus
                />
              </div>
            ) : (
              <div className="field">
                <label className="field-label" htmlFor="totp">رمز من ٦ أرقام</label>
                <input
                  id="totp" className="num" inputMode="numeric" maxLength={6} value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  required autoFocus
                />
              </div>
            )}
            {error && <div className="alert alert-critical">{error}</div>}
            <button
              type="submit" className="btn btn-primary btn-lg" style={{ width: '100%' }}
              disabled={busy || (useBackup && step === 'totp_required' ? !backupCode.trim() : !totpValid)}
            >
              تأكيد
            </button>
            {step === 'totp_required' && (
              <button type="button" className="btn-text login-forgot" onClick={() => { setUseBackup((v) => !v); setError(null) }}>
                {useBackup ? 'استخدم رمز تطبيق المصادقة' : 'فقدت جهاز المصادقة؟ استخدم رمزاً احتياطياً'}
              </button>
            )}
          </form>
        )}
      </div>
    </div>
  )
}
