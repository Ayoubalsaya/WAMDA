import { useEffect, useState } from 'react'
import type { ClientSearchResult } from '../api/types'
import { ClientPanel } from './journal/ClientPanel'
import { OperationsList } from './journal/OperationsList'
import { OperationForm } from './journal/OperationForm'
import { ExchangeWizard } from './journal/ExchangeWizard'
import './JournalScreen.css'

// الاثنتا عشرة عملية كلها مدعومة الآن (المرحلتان ٥+٧) — القائمة هنا حارس
// بسيط ضد أي قيمة requestedOpType غير متوقعة، لا تعبير عن نقص فعلي.
const SUPPORTED_TABS = new Set([
  'RECEIPT', 'PAYMENT', 'EXCHANGE', 'CASH_TRANSFER', 'REMIT_OUT', 'EXPENSE',
  'SWIFT_OUT', 'SWIFT_IN', 'SWIFT_RETURN', 'LOCAL_MOVE', 'OPENING', 'ADJUSTMENT',
])

interface JournalScreenProps {
  currentUserRole: 'ADMIN' | 'ACCOUNTANT'
  canCreateClient?: boolean
  requestedOpType?: string | null
  onRequestedOpTypeConsumed?: () => void
}

export function JournalScreen({ currentUserRole, canCreateClient = false, requestedOpType, onRequestedOpTypeConsumed }: JournalScreenProps) {
  const [client, setClient] = useState<ClientSearchResult | null>(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [unsupportedNotice, setUnsupportedNotice] = useState<string | null>(null)
  const [balanceRefreshToken, setBalanceRefreshToken] = useState(0)
  // سجل العمليات (OperationsList) يملك جلب بياناته بنفسه الآن (تنقّل
  // بالتاريخ/نطاق مستقل) — هذا فقط يُخبره "شيء تغيَّر، أعد الجلب".
  const [entriesRefreshToken, setEntriesRefreshToken] = useState(0)

  useEffect(() => {
    if (!requestedOpType) return
    if (!SUPPORTED_TABS.has(requestedOpType)) {
      setUnsupportedNotice(requestedOpType)
    }
    onRequestedOpTypeConsumed?.()
  }, [requestedOpType, onRequestedOpTypeConsumed])

  function onEntryPosted() {
    setEntriesRefreshToken((v) => v + 1)
    setBalanceRefreshToken((v) => v + 1)
  }

  return (
    <div className="journal-screen">
      <h2 className="screen-title" style={{ marginBottom: 16 }}>دفتر اليومية</h2>
      {unsupportedNotice && (
        <div className="alert alert-info" style={{ marginBottom: 16 }}>
          نوع عملية غير معروف ({unsupportedNotice}).
          <button type="button" className="btn-text" style={{ marginInlineStart: 8 }} onClick={() => setUnsupportedNotice(null)}>إغلاق</button>
        </div>
      )}
      <div className="journal-columns">
        {/* ترتيب DOM يطابق تدفّق RTL: العمود الأول = الأيمن (العميل) */}
        <ClientPanel selected={client} onSelect={setClient} refreshToken={balanceRefreshToken} canCreateClient={canCreateClient} />
        <OperationForm
          client={client}
          currentUserRole={currentUserRole}
          onPosted={onEntryPosted}
          onOpenWizard={() => setWizardOpen(true)}
          requestedTab={requestedOpType && SUPPORTED_TABS.has(requestedOpType) ? requestedOpType : null}
        />
        <OperationsList currentUserRole={currentUserRole} refreshToken={entriesRefreshToken} />
      </div>
      {wizardOpen && (
        <ExchangeWizard
          client={client}
          onClose={() => setWizardOpen(false)}
          onPosted={onEntryPosted}
        />
      )}
    </div>
  )
}
