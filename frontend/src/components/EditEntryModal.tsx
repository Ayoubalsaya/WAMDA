import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ClientDetail, ClientSearchResult, EditResponse } from '../api/types'
import { OperationForm } from '../screens/journal/OperationForm'
import './EditEntryModal.css'

// أ: "شاشة تفاصيل القيد" ← تعديل — نافذة واحدة تُستدعى من الأماكن الأربعة
// (عمليات اليوم · كشف حساب العميل · البحث الذكي · كل مكان آخر يعرض
// عملية) بدل أربع نسخ. تُعيد استخدام OperationForm نفسه بوضع 'edit' —
// لا نموذج ثانٍ موازٍ لكل نوع عملية.

interface EditEntryModalProps {
  entryId: number
  operationType: string
  clientId: number | null
  onClose: () => void
  onSaved: (result: EditResponse) => void
}

export function EditEntryModal({ entryId, operationType, clientId, onClose, onSaved }: EditEntryModalProps) {
  const [client, setClient] = useState<ClientSearchResult | null>(null)
  const [loading, setLoading] = useState(clientId !== null)

  useEffect(() => {
    if (clientId === null) {
      setLoading(false)
      return
    }
    let cancelled = false
    void api.get<ClientDetail>(`/clients/${clientId}`).then((detail) => {
      if (!cancelled) {
        setClient(detail)
        setLoading(false)
      }
    })
    return () => { cancelled = true }
  }, [clientId])

  return (
    <div className="modal-veil" role="dialog" aria-modal="true" aria-label="تعديل العملية" onClick={onClose}>
      <div className="edit-entry-modal" onClick={(e) => e.stopPropagation()}>
        {loading ? (
          <div className="card"><p className="text-muted">...جارٍ التحميل</p></div>
        ) : (
          <OperationForm
            client={client}
            currentUserRole="ADMIN"
            mode="edit"
            editEntryId={entryId}
            requestedTab={operationType}
            onOpenWizard={() => {}}
            onPosted={() => {}}
            onEdited={onSaved}
            onCancelEdit={onClose}
          />
        )}
      </div>
    </div>
  )
}
