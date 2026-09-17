import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { CancelResponse, CommentOut, HistoryResponse } from '../api/types'

// ═══ إلغاء ═══

interface CancelButtonProps {
  entryId: number
  chainRef?: string | null
  onCancelled: () => void
  className?: string
}

export function CancelButton({ entryId, chainRef, onCancelled, className }: CancelButtonProps) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await api.post<CancelResponse>(`/operations/${entryId}/cancel`, { reason })
      setOpen(false)
      setReason('')
      onCancelled()
      if (result.chain_cascade) {
        // إعلام بصري بسيط بعد الإغلاق — النافذة أُغلقت بالفعل فلا داعٍ لحجب التدفّق
        window.setTimeout(() => alert('أُلغيت السلسلة كاملة — كل خطواتها معاً.'), 50)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر الإلغاء')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button type="button" className={className ?? 'btn-text'} onClick={() => setOpen(true)}>
        إلغاء
      </button>
      {open && (
        <div className="modal-veil" role="dialog" aria-modal="true" onClick={() => !busy && setOpen(false)}>
          <form className="card new-op-panel" style={{ width: 420 }} onClick={(e) => e.stopPropagation()} onSubmit={submit}>
            <h3 className="card-title" style={{ marginBottom: 12 }}>إلغاء العملية</h3>
            {chainRef && (
              <div className="alert alert-warning" style={{ marginBottom: 12 }}>
                هذه العملية ضمن سلسلة ({chainRef}) — إلغاؤها يُلغي السلسلة كاملة بكل خطواتها.
              </div>
            )}
            <div className="field" style={{ marginBottom: 16 }}>
              <label className="field-label" htmlFor="cancel-reason">السبب (إلزامي)</label>
              <textarea
                id="cancel-reason" value={reason} onChange={(e) => setReason(e.target.value)}
                required autoFocus rows={3} style={{ width: '100%' }}
              />
            </div>
            {error && <div className="alert alert-critical" style={{ marginBottom: 12 }}>{error}</div>}
            <div className="op-row">
              <button type="button" className="btn btn-secondary" onClick={() => setOpen(false)} disabled={busy}>تراجع</button>
              <button type="submit" className="btn btn-primary" style={{ flex: 1 }} disabled={busy || !reason.trim()}>
                تأكيد الإلغاء
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  )
}

// ═══ شارة "معدَّلة" + السجل الكامل ═══

const KIND_LABELS: Record<string, string> = { original: 'العملية الأصلية', reversal: 'قيد العكس', replacement: 'العملية الجديدة' }
const STATUS_LABELS: Record<string, string> = { POSTED: 'مُرحَّل', REVERSED: 'مُلغى', DRAFT: 'مسوَّدة' }

export function EditedBadge({ entryId }: { entryId: number }) {
  const [open, setOpen] = useState(false)
  const [history, setHistory] = useState<HistoryResponse | null>(null)

  async function show(e: React.MouseEvent | React.KeyboardEvent) {
    e.stopPropagation()
    setOpen(true)
    if (!history) {
      const h = await api.get<HistoryResponse>(`/operations/${entryId}/history`)
      setHistory(h)
    }
  }

  return (
    <>
      {/* span لا button — يُعرَض أحياناً داخل زر تبديل الصف نفسه (عمليات
          اليوم)، وbutton داخل button غير صالح HTML ويكسر النقر فعلياً؛
          stopPropagation يمنع تفعيل تبديل الصف حين يكون هذا هو الوالد. */}
      <span
        role="button" tabIndex={0} className="badge badge-status-reversed"
        style={{ cursor: 'pointer' }} onClick={show}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') show(e) }}
      >
        معدَّلة
      </span>
      {open && (
        <div className="modal-veil" role="dialog" aria-modal="true" onClick={() => setOpen(false)}>
          <div className="card new-op-panel" style={{ width: 480 }} onClick={(e) => e.stopPropagation()}>
            <h3 className="card-title" style={{ marginBottom: 12 }}>السجل الكامل</h3>
            {!history ? (
              <p className="text-muted">...جارٍ التحميل</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {history.steps.map((s) => (
                  <div key={s.entry_id} className="today-op-detail" style={{ padding: 10 }}>
                    <div className="op-row" style={{ justifyContent: 'space-between' }}>
                      <strong>{KIND_LABELS[s.kind] ?? s.kind}</strong>
                      <span className="text-muted" style={{ fontSize: 12 }}>{STATUS_LABELS[s.status] ?? s.status}</span>
                    </div>
                    <div className="num text-muted" style={{ fontSize: 12 }}>{s.entry_no}</div>
                    <div style={{ fontSize: 12.5, marginTop: 4 }}>
                      {s.created_by_name} — {new Date(s.created_at).toLocaleString('ar-LY')}
                    </div>
                    {s.reason && <div style={{ fontSize: 12.5, marginTop: 4 }}>السبب: {s.reason}</div>}
                  </div>
                ))}
              </div>
            )}
            <div className="op-row" style={{ marginTop: 16 }}>
              <button type="button" className="btn btn-secondary" style={{ flex: 1 }} onClick={() => setOpen(false)}>إغلاق</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ═══ تعليقات لاحقة ═══

export function CommentsPanel({ entryId }: { entryId: number }) {
  const [comments, setComments] = useState<CommentOut[] | null>(null)
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)

  async function reload() {
    setComments(await api.get<CommentOut[]>(`/operations/${entryId}/comments`))
  }

  useEffect(() => { void reload() }, [entryId])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!body.trim()) return
    setBusy(true)
    try {
      await api.post(`/operations/${entryId}/comments`, { body })
      setBody('')
      await reload()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ marginTop: 10 }}>
      <div className="text-muted" style={{ fontSize: 12, marginBottom: 6 }}>التعليقات</div>
      {comments === null ? (
        <p className="text-muted" style={{ fontSize: 12 }}>...جارٍ التحميل</p>
      ) : comments.length === 0 ? (
        <p className="text-muted" style={{ fontSize: 12 }}>لا تعليقات بعد</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 8 }}>
          {comments.map((c) => (
            <div key={c.id} style={{ fontSize: 12.5, borderRight: '2px solid var(--sky-500)', paddingRight: 8 }}>
              <div>{c.body}</div>
              <div className="text-muted" style={{ fontSize: 11 }}>
                {c.created_by_name} — {new Date(c.created_at).toLocaleString('ar-LY')}
              </div>
            </div>
          ))}
        </div>
      )}
      <form onSubmit={submit} className="op-row" style={{ gap: 6 }}>
        <input
          value={body} onChange={(e) => setBody(e.target.value)} placeholder="أضف تعليقاً..."
          style={{ flex: 1 }}
        />
        <button type="submit" className="btn btn-secondary btn-sm" disabled={busy || !body.trim()}>إضافة</button>
      </form>
    </div>
  )
}
