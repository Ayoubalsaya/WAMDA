import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { BackupCodesStatus } from '../../api/types'
import { BackupCodesPanel } from '../../components/BackupCodesPanel'
import { FormGuide } from '../journal/journalUi'
import { useFormErrors } from '../../hooks/useFormErrors'

// الإعدادات ← الأمان (٢٠٢٦-١٠-٠٣): عدد الرموز الاحتياطية المتبقّية، تنبيه عند ٣ أو أقل، وإعادة الإنشاء (تُبطل كل السابقة).
// إعادة الإنشاء تتطلب كلمة المرور الحالية، والرموز الجديدة تُعرض مرة واحدة فقط.
export function SecurityTab() {
  const [status, setStatus] = useState<BackupCodesStatus | null>(null)
  const [codes, setCodes] = useState<string[] | null>(null)
  const [password, setPassword] = useState('')
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const { ref, error, setError, report, portals } = useFormErrors({ password: 'كلمة المرور' })

  async function load() {
    setStatus(await api.get<BackupCodesStatus>('/auth/backup-codes'))
  }
  useEffect(() => { void load() }, [])

  async function regenerate(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await api.post<{ codes: string[] }>('/auth/backup-codes/regenerate', { password })
      setCodes(res.codes)
      setPassword('')
      setAsking(false)
    } catch (err) {
      report(err, 'تعذّرت إعادة إنشاء الرموز')
    } finally {
      setBusy(false)
    }
  }

  if (codes) {
    return (
      <div style={{ maxWidth: 520 }}>
        <BackupCodesPanel
          codes={codes} title="رموزك الاحتياطية الجديدة" continueLabel="تم"
          onAcknowledged={() => { setCodes(null); void load() }}
        />
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 520 }} ref={ref}>
      <h3 className="card-title" style={{ marginBottom: 8 }}>الرموز الاحتياطية للمصادقة</h3>
      <p className="text-muted" style={{ marginBottom: 12 }}>
        عشرة رموز، كل منها لمرة واحدة، تدخل بها إن فقدت جهاز المصادقة (مع كلمة المرور دائماً). إعادة الإنشاء تُبطل كل الرموز السابقة.
      </p>
      {status && (
        <>
          <div className="result-card" style={{ marginBottom: 12 }} data-testid="backup-codes-status">
            <div className="result-row result-final">
              <span>الرموز المتبقّية</span>
              <span className="num" data-testid="backup-codes-remaining">{status.remaining} من {status.total}</span>
            </div>
          </div>
          {status.low && (
            <FormGuide tone="warning" title="رموزك الاحتياطية على وشك النفاد">
              {status.remaining === 0 ? 'لا رموز متبقية — أنشئ رموزاً جديدة الآن.' : `تبقّى ${status.remaining} فقط — أنشئ رموزاً جديدة.`}
            </FormGuide>
          )}
        </>
      )}
      {!asking ? (
        <button type="button" className="btn btn-primary" style={{ marginTop: 12 }} onClick={() => setAsking(true)}>
          إنشاء رموز جديدة
        </button>
      ) : (
        <form onSubmit={regenerate} style={{ marginTop: 12 }}>
          <div className="field" style={{ marginBottom: 12 }}>
            <label className="field-label" htmlFor="regen-password">كلمة المرور الحالية</label>
            <input id="regen-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus />
          </div>
          {error && <div className="alert alert-critical" style={{ marginBottom: 12 }}>{error}</div>}
          {portals}
          <FormGuide tone="warning">ستُبطَل كل الرموز السابقة فور الإنشاء.</FormGuide>
          <div className="op-row" style={{ marginTop: 12 }}>
            <button type="button" className="btn btn-secondary" onClick={() => { setAsking(false); setPassword(''); setError(null) }}>إلغاء</button>
            <button type="submit" className="btn btn-primary" style={{ flex: 1 }} disabled={busy || !password}>تأكيد وإنشاء</button>
          </div>
        </form>
      )}
    </div>
  )
}
