import { useEffect, useState } from 'react'
import { Copy, MessageCircle, X } from 'lucide-react'
import { api, ApiError } from '../../api/client'
import type { ClientPortalInviteCreatedResponse, ClientPortalStatus, ClientPortalStatusResponse } from '../../api/types'

interface ClientPortalSectionProps {
  clientId: number
  clientName: string
  clientPhone: string | null
}

const STATUS_LABEL: Record<ClientPortalStatus, string> = {
  NOT_ENABLED: 'غير مفعّلة',
  INVITE_PENDING: 'دعوة معلّقة',
  INVITE_EXPIRED: 'دعوة منتهية',
  ACTIVE: 'مفعّلة',
  LOCKED: 'مقفلة',
  DISABLED: 'معطّلة',
}

const STATUS_BADGE_CLASS: Record<ClientPortalStatus, string> = {
  NOT_ENABLED: 'badge-other',
  INVITE_PENDING: 'badge-status-draft',
  INVITE_EXPIRED: 'badge-status-reversed',
  ACTIVE: 'badge-status-posted',
  LOCKED: 'badge-status-reversed',
  DISABLED: 'badge-other',
}

function formatTimeLeft(expiresAtIso: string): string {
  const ms = new Date(expiresAtIso).getTime() - Date.now()
  if (ms <= 0) return 'منتهية'
  const hours = Math.floor(ms / 3_600_000)
  if (hours >= 1) return `تنتهي خلال ${hours} ساعة`
  const minutes = Math.max(1, Math.floor(ms / 60_000))
  return `تنتهي خلال ${minutes} دقيقة`
}

function whatsappMessage(clientName: string, inviteUrl: string): string {
  return (
    `مرحباً ${clientName}،\n` +
    `هذا رابط دخولك لبوابة ومضة لتعيين كلمة مرورك:\n${inviteUrl}\n` +
    `الرابط صالح ٤٨ ساعة فقط ولمرة واحدة — لا تشاركه مع أي شخص آخر.`
  )
}

export function ClientPortalSection({ clientId, clientName, clientPhone }: ClientPortalSectionProps) {
  const [status, setStatus] = useState<ClientPortalStatusResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<'reset' | 'disable' | null>(null)
  const [revealed, setRevealed] = useState<ClientPortalInviteCreatedResponse | null>(null)
  const [copied, setCopied] = useState(false)

  async function reload() {
    const data = await api.get<ClientPortalStatusResponse>(`/clients/${clientId}/portal`)
    setStatus(data)
  }

  useEffect(() => {
    void reload()
    setConfirming(null)
    setRevealed(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId])

  async function runAction(action: 'enable' | 'invite' | 'reset' | 'disable' | 'unlock') {
    setBusy(true)
    setError(null)
    try {
      if (action === 'disable' || action === 'unlock') {
        await api.post(`/clients/${clientId}/portal/${action}`)
      } else {
        const created = await api.post<ClientPortalInviteCreatedResponse>(`/clients/${clientId}/portal/${action}`)
        setRevealed(created)
        setCopied(false)
      }
      setConfirming(null)
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر تنفيذ الإجراء')
    } finally {
      setBusy(false)
    }
  }

  async function copyLink() {
    if (!revealed) return
    try {
      await navigator.clipboard.writeText(revealed.invite_url)
      setCopied(true)
    } catch {
      setError('تعذّر نسخ الرابط — انسخه يدوياً')
    }
  }

  function whatsappHref(): string {
    if (!revealed) return '#'
    const text = encodeURIComponent(whatsappMessage(clientName, revealed.invite_url))
    const phoneDigits = clientPhone?.replace(/[^\d+]/g, '')
    return phoneDigits ? `https://wa.me/${phoneDigits}?text=${text}` : `https://wa.me/?text=${text}`
  }

  if (!status) return null

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="clients-header" style={{ marginBottom: 12 }}>
        <div className="card-title">بوابة العميل</div>
        <span className={`badge ${STATUS_BADGE_CLASS[status.status]}`}>{STATUS_LABEL[status.status]}</span>
      </div>

      <div className="text-muted" style={{ fontSize: 'var(--fs-sm)', marginBottom: 12 }}>
        آخر دخول: {status.last_login_at ? new Date(status.last_login_at).toLocaleString('ar-LY') : 'لم يدخل بعد'}
        {status.invite_expires_at && (status.status === 'INVITE_PENDING' || status.status === 'INVITE_EXPIRED') && (
          <> · {formatTimeLeft(status.invite_expires_at)}</>
        )}
      </div>

      {error && <div className="alert alert-critical" style={{ marginBottom: 12 }}>{error}</div>}

      {revealed && (
        <div className="alert alert-warning" style={{ marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <strong>لن يظهر هذا الرابط مرة أخرى — انسخه أو أرسله الآن</strong>
          <div className="num" style={{ wordBreak: 'break-all', fontSize: 'var(--fs-xs)' }}>{revealed.invite_url}</div>
          <div className="op-row" style={{ gap: 8 }}>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => void copyLink()}>
              <Copy size={14} /> {copied ? 'تم النسخ' : 'نسخ الرابط'}
            </button>
            <a href={whatsappHref()} target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">
              <MessageCircle size={14} /> إرسال عبر واتساب
            </a>
            <button type="button" className="mini-icon" title="إغلاق" onClick={() => setRevealed(null)}>
              <X size={16} strokeWidth={2} />
            </button>
          </div>
        </div>
      )}

      <div className="op-row" style={{ gap: 8 }}>
        {status.status === 'NOT_ENABLED' && (
          <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void runAction('enable')}>
            تفعيل + إنشاء دعوة
          </button>
        )}
        {status.status === 'DISABLED' && (
          <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void runAction('enable')}>
            تفعيل + دعوة جديدة
          </button>
        )}
        {(status.status === 'INVITE_PENDING' || status.status === 'INVITE_EXPIRED') && (
          <>
            <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void runAction('invite')}>
              رابط جديد
            </button>
            {confirming === 'disable' ? (
              <span className="op-row" style={{ gap: 6 }}>
                <span className="text-muted" style={{ fontSize: 'var(--fs-xs)' }}>تعطيل البوابة؟</span>
                <button type="button" className="btn btn-danger btn-sm" disabled={busy} onClick={() => void runAction('disable')}>تأكيد</button>
                <button type="button" className="btn-text" onClick={() => setConfirming(null)}>إلغاء</button>
              </span>
            ) : (
              <button type="button" className="btn-text" disabled={busy} onClick={() => setConfirming('disable')}>تعطيل</button>
            )}
          </>
        )}
        {(status.status === 'ACTIVE' || status.status === 'LOCKED') && (
          <>
            {status.status === 'LOCKED' && (
              <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void runAction('unlock')}>
                فك القفل
              </button>
            )}
            {confirming === 'reset' ? (
              <span className="op-row" style={{ gap: 6 }}>
                <span className="text-muted" style={{ fontSize: 'var(--fs-xs)' }}>إعادة التعيين تُبطل كلمة المرور الحالية وتُنهي جلساته — متأكد؟</span>
                <button type="button" className="btn btn-danger btn-sm" disabled={busy} onClick={() => void runAction('reset')}>تأكيد</button>
                <button type="button" className="btn-text" onClick={() => setConfirming(null)}>إلغاء</button>
              </span>
            ) : (
              <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setConfirming('reset')}>إعادة تعيين</button>
            )}
            {confirming === 'disable' ? (
              <span className="op-row" style={{ gap: 6 }}>
                <span className="text-muted" style={{ fontSize: 'var(--fs-xs)' }}>تعطيل البوابة؟</span>
                <button type="button" className="btn btn-danger btn-sm" disabled={busy} onClick={() => void runAction('disable')}>تأكيد</button>
                <button type="button" className="btn-text" onClick={() => setConfirming(null)}>إلغاء</button>
              </span>
            ) : (
              <button type="button" className="btn-text" disabled={busy} onClick={() => setConfirming('disable')}>تعطيل</button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
