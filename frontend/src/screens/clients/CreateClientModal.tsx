import { useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { ClientDetail } from '../../api/types'

interface CreateClientModalProps {
  onClose: () => void
  onCreated: (client: ClientDetail) => void
}

export function CreateClientModal({ onClose, onCreated }: CreateClientModalProps) {
  const [code, setCode] = useState('')
  const [nameAr, setNameAr] = useState('')
  const [phone, setPhone] = useState('')
  const [idNumber, setIdNumber] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const client = await api.post<ClientDetail>('/clients', {
        code, name_ar: nameAr, phone: phone || undefined, id_number: idNumber || undefined,
      })
      onCreated(client)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذّر إنشاء العميل')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-veil" role="dialog" aria-modal="true" onClick={onClose}>
      <form className="card new-op-panel" style={{ width: 420 }} onClick={(e) => e.stopPropagation()} onSubmit={submit}>
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
        {error && <div className="alert alert-critical" style={{ marginBottom: 12 }}>{error}</div>}
        <div className="op-row">
          <button type="button" className="btn btn-secondary" onClick={onClose}>إلغاء</button>
          <button type="submit" className="btn btn-primary" style={{ flex: 1 }} disabled={busy}>حفظ</button>
        </div>
      </form>
    </div>
  )
}
