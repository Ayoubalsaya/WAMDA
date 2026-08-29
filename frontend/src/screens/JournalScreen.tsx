import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ClientSearchResult, JournalEntryOut } from '../api/types'
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
  requestedOpType?: string | null
  onRequestedOpTypeConsumed?: () => void
}

export function JournalScreen({ currentUserRole, requestedOpType, onRequestedOpTypeConsumed }: JournalScreenProps) {
  const [client, setClient] = useState<ClientSearchResult | null>(null)
  const [entries, setEntries] = useState<JournalEntryOut[]>([])
  const [loadingEntries, setLoadingEntries] = useState(true)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [unsupportedNotice, setUnsupportedNotice] = useState<string | null>(null)
  const [balanceRefreshToken, setBalanceRefreshToken] = useState(0)

  useEffect(() => {
    if (!requestedOpType) return
    if (!SUPPORTED_TABS.has(requestedOpType)) {
      setUnsupportedNotice(requestedOpType)
    }
    onRequestedOpTypeConsumed?.()
  }, [requestedOpType, onRequestedOpTypeConsumed])

  const reloadEntries = useCallback(async () => {
    setLoadingEntries(true)
    const rows = await api.get<JournalEntryOut[]>('/journal/entries')
    setEntries(rows)
    setLoadingEntries(false)
  }, [])

  useEffect(() => {
    void reloadEntries()
  }, [reloadEntries])

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
        <ClientPanel selected={client} onSelect={setClient} refreshToken={balanceRefreshToken} />
        <OperationForm
          client={client}
          currentUserRole={currentUserRole}
          onPosted={() => { void reloadEntries(); setBalanceRefreshToken((v) => v + 1) }}
          onOpenWizard={() => setWizardOpen(true)}
          requestedTab={requestedOpType && SUPPORTED_TABS.has(requestedOpType) ? requestedOpType : null}
        />
        <OperationsList entries={entries} loading={loadingEntries} />
      </div>
      {wizardOpen && (
        <ExchangeWizard
          client={client}
          onClose={() => setWizardOpen(false)}
          onPosted={() => { void reloadEntries(); setBalanceRefreshToken((v) => v + 1) }}
        />
      )}
    </div>
  )
}
