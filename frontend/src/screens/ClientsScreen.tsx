import { useState } from 'react'
import { ClientsListView } from './clients/ClientsListView'
import { ClientDetailView } from './clients/ClientDetailView'
import { CreateClientModal } from './clients/CreateClientModal'
import './clients/ClientsScreen.css'

interface ClientsScreenProps {
  currentUserRole: 'ADMIN' | 'ACCOUNTANT'
}

export function ClientsScreen({ currentUserRole }: ClientsScreenProps) {
  const [selectedClientId, setSelectedClientId] = useState<number | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [refreshToken, setRefreshToken] = useState(0)

  return (
    <>
      {selectedClientId ? (
        <ClientDetailView
          clientId={selectedClientId} currentUserRole={currentUserRole}
          onBack={() => { setSelectedClientId(null); setRefreshToken((v) => v + 1) }}
        />
      ) : (
        <ClientsListView key={refreshToken} onSelect={setSelectedClientId} onCreate={() => setCreateOpen(true)} />
      )}
      {createOpen && (
        <CreateClientModal
          onClose={() => setCreateOpen(false)}
          onCreated={(client) => { setCreateOpen(false); setSelectedClientId(client.id) }}
          onPickExisting={(client) => { setCreateOpen(false); setSelectedClientId(client.id) }}
        />
      )}
    </>
  )
}
