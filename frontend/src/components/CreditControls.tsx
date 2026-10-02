import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import Decimal from 'decimal.js'
import { api, ApiError } from '../api/client'
import type { ClientDetail, CreditModeChange, CreditStatus } from '../api/types'
import { useReferenceData } from '../hooks/useReferenceData'

// ائتمان بلا سقف (٢٠٢٦-١٠-٠٣): شارة الحالة + زر واحد لكل العملات (عدسة العميل وشاشة العميل). الحالة محسوبة من أوضاع العملات.
export const CREDIT_STATUS_LABEL: Record<CreditStatus, string> = { OPEN: 'ائتمان مفتوح', STOPPED: 'متوقف', PARTIAL: 'جزئي' }
const BADGE_CLASS: Record<CreditStatus, string> = { OPEN: 'badge-status-posted', STOPPED: 'badge-status-reversed', PARTIAL: 'badge-status-draft' }

export function CreditStatusBadge({ status }: { status: CreditStatus }) {
  return <span className={`badge ${BADGE_CLASS[status]}`} data-testid="credit-status-badge" data-status={status}>{CREDIT_STATUS_LABEL[status]}</span>
}

interface CreditControlsProps {
  clientId: number
  status: CreditStatus
  onChanged: (status: CreditStatus) => void
}

type Pending = { kind: 'UNLIMITED' | 'NONE'; limits: string[]; debts: string[] }

// الزر لمن يملك صلاحية تعديل الائتمان فقط (يتحكم الأب بعرضه؛ الخادم يفرضه). لا يمسّ حالة أي نموذج مفتوح.
export function CreditControls({ clientId, status, onChanged }: CreditControlsProps) {
  const { currencies } = useReferenceData()
  const [pending, setPending] = useState<Pending | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { setPending(null); setError(null) }, [clientId])

  function fmt(amount: string, code: string): string {
    const decimals = currencies.find((c) => c.code === code)?.decimals ?? 2
    return new Decimal(amount).abs().toNumber().toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
  }

  async function apply(kind: 'UNLIMITED' | 'NONE') {
    setBusy(true)
    setError(null)
    try {
      const res = await api.put<CreditModeChange>(`/clients/${clientId}/credit-mode`, { mode: kind })
      onChanged(res.credit_status)
      setPending(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر تغيير الائتمان')
    } finally {
      setBusy(false)
    }
  }

  // الضغطة الأولى تجلب الوضع الحالي لتبني التأكيد: «السماح» يحتاج تأكيداً فقط إن وُجدت حدود مخصصة تُستبدل؛ «الإيقاف» دائماً بتأكيد واحد
  async function request(kind: 'UNLIMITED' | 'NONE') {
    setError(null)
    setBusy(true)
    try {
      const detail = await api.get<ClientDetail>(`/clients/${clientId}`)
      const limits = detail.credit_limits
        .filter((l) => l.mode === 'LIMIT' && l.limit_amount !== null)
        .map((l) => `سيُلغى حد ${fmt(l.limit_amount as string, l.currency_code)} ${l.currency_code} ويصبح بلا سقف`)
      const debts = detail.balances.filter((b) => new Decimal(b.balance).lt(0)).map((b) => `${fmt(b.balance, b.currency_code)} ${b.currency_code}`)
      if (kind === 'UNLIMITED' && limits.length === 0) {
        setBusy(false)
        await apply('UNLIMITED')
        return
      }
      setPending({ kind, limits, debts: Array.from(new Set(debts)) })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر قراءة بيانات الائتمان')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="credit-controls" data-testid="credit-controls">
      <div className="credit-controls-actions">
        {status !== 'OPEN' && (
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void request('UNLIMITED')}>السماح بائتمان</button>
        )}
        {status !== 'STOPPED' && (
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void request('NONE')}>إيقاف الائتمان</button>
        )}
      </div>
      {error && !pending && <div className="alert alert-critical" style={{ marginTop: 8 }}>{error}</div>}
      {pending && createPortal(
        <div className="modal-veil" role="dialog" aria-modal="true" aria-label="تأكيد تغيير الائتمان" onClick={() => !busy && setPending(null)}>
          <div className="card new-op-panel" style={{ width: 460 }} onClick={(e) => e.stopPropagation()} data-testid="credit-confirm">
            <h3 className="card-title" style={{ marginBottom: 12 }}>
              {pending.kind === 'UNLIMITED' ? 'السماح بائتمان بلا سقف' : 'إيقاف الائتمان'}
            </h3>
            {pending.kind === 'UNLIMITED' ? (
              <>
                <p style={{ marginBottom: 8 }}>سيُسمح للعميل برصيد سالب <strong>بلا حد</strong> في كل العملات.</p>
                {pending.limits.map((l) => <div className="alert alert-warning" key={l} style={{ marginBottom: 8 }}>{l}</div>)}
              </>
            ) : (
              <>
                <p style={{ marginBottom: 8 }}>سيُمنع الرصيد السالب في كل العملات.</p>
                {pending.debts.length > 0 && (
                  <div className="alert alert-warning" style={{ marginBottom: 8 }}>
                    للعميل دين حالي ({pending.debts.join(' · ')}): لن يُرفض الإيقاف، لكن العمليات التي تزيد الدين ستُرفض.
                  </div>
                )}
              </>
            )}
            {error && <div className="alert alert-critical" style={{ marginBottom: 8 }}>{error}</div>}
            <div className="op-row" style={{ marginTop: 12 }}>
              <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => setPending(null)}>تراجع</button>
              <button type="button" className="btn btn-primary" style={{ flex: 1 }} disabled={busy} onClick={() => void apply(pending.kind)}>تأكيد</button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  )
}
