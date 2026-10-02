import { useState } from 'react'
import { api } from '../../api/client'
import type { ClientDetail, ClientSearchResult, SimilarClient } from '../../api/types'
import { useFormErrors } from '../../hooks/useFormErrors'

interface CreateClientModalProps {
  onClose: () => void
  onCreated: (client: ClientDetail) => void
  // الإضافة السريعة من دفتر اليومية (٢٠٢٦-١٠-٠٢): الاسم معبّأ من نص البحث، والإنشاء بزر «حفظ» الصريح فقط
  // (الإنتر داخل الحقول لا يُرسل النموذج — لا اختصار لوحة مفاتيح ينشئ عميلاً)
  initialName?: string
  explicitSubmitOnly?: boolean
  // اختيار عميل موجود من تنبيه التشابه (بدل إنشاء مكرَّر) — بلا هذه الخاصية لا يظهر زر الاختيار
  onPickExisting?: (client: ClientSearchResult) => void
}

export function CreateClientModal({ onClose, onCreated, initialName = '', explicitSubmitOnly = false, onPickExisting }: CreateClientModalProps) {
  const [code, setCode] = useState('')
  const [nameAr, setNameAr] = useState(initialName)
  const [similar, setSimilar] = useState<SimilarClient[] | null>(null)
  const [phone, setPhone] = useState('')
  const [idNumber, setIdNumber] = useState('')
  const [busy, setBusy] = useState(false)
  const { ref: formRef, error, setError, report, portals } = useFormErrors({ code: 'كود العميل', name_ar: 'الاسم', phone: 'الهاتف', id_number: 'رقم الهوية' })

  // منع التكرار: قبل أول حفظ تُعرض الأسماء المشابهة (بعد توحيد الكتابة العربية في الخادم) أو بنفس الهاتف
  async function submit(e: React.FormEvent, skipSimilarCheck = false) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (!skipSimilarCheck) {
        const params = new URLSearchParams({ name: nameAr })
        if (phone) params.set('phone', phone)
        const rows = await api.get<SimilarClient[]>(`/clients/similar?${params}`)
        if (rows.length > 0) {
          setSimilar(rows)
          return
        }
      }
      const client = await api.post<ClientDetail>('/clients', {
        code, name_ar: nameAr, phone: phone || undefined, id_number: idNumber || undefined,
      })
      onCreated(client)
    } catch (err) {
      report(err, 'تعذّر إنشاء العميل')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-veil" role="dialog" aria-modal="true" onClick={onClose}>
      <form
        ref={formRef} className="card new-op-panel" style={{ width: 420 }} onClick={(e) => e.stopPropagation()} onSubmit={submit}
        onInput={() => setSimilar(null)}
        onKeyDown={explicitSubmitOnly ? (e) => { if (e.key === 'Enter' && (e.target as HTMLElement).tagName === 'INPUT') e.preventDefault() } : undefined}
      >
        <h3 className="card-title" style={{ marginBottom: 16 }}>عميل جديد</h3>
        <div className="field" style={{ marginBottom: 12 }}>
          <label className="field-label" htmlFor="new-client-code">كود العميل</label>
          <input id="new-client-code" value={code} onChange={(e) => setCode(e.target.value)} required autoFocus />
        </div>
        <div className="field" style={{ marginBottom: 12 }}>
          <label className="field-label" htmlFor="new-client-name">الاسم</label>
          <input id="new-client-name" value={nameAr} onChange={(e) => setNameAr(e.target.value)} required />
        </div>
        <div className="field" style={{ marginBottom: 12 }}>
          <label className="field-label" htmlFor="new-client-phone">الهاتف (اختياري)</label>
          <input id="new-client-phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
        </div>
        <div className="field" style={{ marginBottom: 16 }}>
          <label className="field-label" htmlFor="new-client-id">رقم الهوية (اختياري)</label>
          <input id="new-client-id" value={idNumber} onChange={(e) => setIdNumber(e.target.value)} />
        </div>
        {similar && (
          <div className="alert alert-warning similar-clients" role="alert" data-testid="similar-clients" style={{ marginBottom: 12, display: 'block' }}>
            <strong>هل تقصد أحد هؤلاء؟</strong>
            <ul style={{ listStyle: 'none', margin: '8px 0', padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {similar.map((c) => (
                <li key={c.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ flex: 1 }}>
                    {c.name_ar} <span className="num text-muted">{c.code}</span>
                    <small className="text-muted"> — {c.reason}</small>
                  </span>
                  {onPickExisting && (
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => onPickExisting(c)}>اختيار</button>
                  )}
                </li>
              ))}
            </ul>
            <button type="button" className="btn btn-muted btn-sm" disabled={busy} onClick={(e) => void submit(e, true)}>
              لا، أنشئ عميلاً جديداً
            </button>
          </div>
        )}
        {error && <div className="alert alert-critical" style={{ marginBottom: 12 }}>{error}</div>}
        {portals}
        <div className="op-row">
          <button type="button" className="btn btn-secondary" onClick={onClose}>إلغاء</button>
          <button type="submit" className="btn btn-primary" style={{ flex: 1 }} disabled={busy}>حفظ</button>
        </div>
      </form>
    </div>
  )
}
