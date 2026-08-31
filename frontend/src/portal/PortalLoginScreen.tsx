import { useState } from 'react'
import { ApiError } from '../api/client'
import type { PortalLoginResponse } from '../api/types'
import { LogoMark } from '../components/LogoMark'
import './PortalLoginScreen.css'

interface PortalLoginScreenProps {
  login: (code: string, password: string) => Promise<PortalLoginResponse>
}

export function PortalLoginScreen({ login }: PortalLoginScreenProps) {
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(code, password)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر تسجيل الدخول')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="portal-login-screen">
      <div className="portal-login-brand">
        <div className="portal-login-logo"><LogoMark size={40} /></div>
        <h1 className="portal-login-name">ومضة</h1>
        <p className="portal-login-tagline">بوابة العميل</p>
      </div>
      <form className="portal-login-form" onSubmit={submit}>
        <div className="field">
          <label className="field-label" htmlFor="portal-code">كود العميل</label>
          <input id="portal-code" value={code} onChange={(e) => setCode(e.target.value)} required autoFocus />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="portal-password">كلمة المرور</label>
          <input id="portal-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        {error && <div className="alert alert-critical">{error}</div>}
        <button type="submit" className="btn btn-primary btn-lg" disabled={busy} style={{ width: '100%' }}>
          دخول
        </button>
      </form>
    </div>
  )
}
