import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from './hooks/useAuth'
import { LoginScreen } from './screens/LoginScreen'
import { ChangePasswordScreen } from './screens/ChangePasswordScreen'
import { JournalScreen } from './screens/JournalScreen'
import { ClientsScreen } from './screens/ClientsScreen'
import { DashboardScreen } from './screens/DashboardScreen'
import { LiquidityScreen } from './screens/LiquidityScreen'
import { AccountsScreen } from './screens/AccountsScreen'
import { ReportsScreen } from './screens/ReportsScreen'
import { ReconciliationScreen } from './screens/ReconciliationScreen'
import { SettingsScreen } from './screens/SettingsScreen'
import { Sidebar, type ScreenId } from './components/Sidebar'
import { NewOperationPanel } from './components/NewOperationPanel'
import { SearchResultsPanel } from './components/SearchResultsPanel'
import { NotificationsBell } from './components/NotificationsBell'
import { type SearchChip, parseSearchQuery } from './lib/parseSearchQuery'
import { useReferenceData } from './hooks/useReferenceData'
import './App.css'

const SCREEN_TITLES: Record<ScreenId, string> = {
  dashboard: 'لوحة التحكم', journal: 'دفتر اليومية', clients: 'العملاء', position: 'مركز السيولة',
  accounts: 'الحسابات', reports: 'التقارير', reconcile: 'المطابقة', settings: 'الإعدادات',
}

// ج-٥: ترتيب Alt+1..8 يطابق ب-١ حرفياً — فوق الزر المركزي ثم تحته
const ALT_SHORTCUT_SCREENS: ScreenId[] = [
  'dashboard', 'journal', 'clients', 'position', 'accounts', 'reports', 'reconcile', 'settings',
]

function Placeholder({ id }: { id: ScreenId }) {
  return (
    <div className="journal-screen">
      <h2 className="screen-title" style={{ marginBottom: 16 }}>{SCREEN_TITLES[id]}</h2>
      <div className="card">
        <p className="text-muted">هذه الشاشة خارج نطاق المراحل المبنية حتى الآن (٥-٨) — تُبنى في مرحلة لاحقة.</p>
      </div>
    </div>
  )
}

export default function App() {
  const { user, checking, login, logout, refresh } = useAuth()
  const [active, setActive] = useState<ScreenId>('journal')
  const [originY, setOriginY] = useState(200)
  const [transitionKey, setTransitionKey] = useState(0)
  const [newOpOpen, setNewOpOpen] = useState(false)
  const [requestedOpType, setRequestedOpType] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchChips, setSearchChips] = useState<SearchChip[]>([])
  const [searchOpen, setSearchOpen] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  const { currencies } = useReferenceData()

  function runSearch() {
    const chips = parseSearchQuery(searchQuery, currencies.map((c) => c.code))
    setSearchChips(chips)
    setSearchOpen(true)
  }

  const navigate = useCallback((id: ScreenId, originEl: HTMLElement | null) => {
    if (originEl) setOriginY(originEl.getBoundingClientRect().top + originEl.getBoundingClientRect().height / 2)
    setActive(id)
    setTransitionKey((k) => k + 1)
    setNewOpOpen(false)
  }, [])

  // ج-٥: اختصارات لوحة المفاتيح الشاملة — Alt+1..8 · Ctrl+N · `/`
  useEffect(() => {
    if (!user) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.altKey && /^[1-8]$/.test(e.key)) {
        e.preventDefault()
        navigate(ALT_SHORTCUT_SCREENS[Number(e.key) - 1], null)
        return
      }
      if (e.ctrlKey && e.key.toLowerCase() === 'n') {
        e.preventDefault()
        setNewOpOpen((v) => !v)
        return
      }
      const target = e.target as HTMLElement | null
      const isTyping = target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
      if (e.key === '/' && !isTyping) {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [user, navigate])

  if (checking) return <div className="app-loading">...جارٍ التحقق من الجلسة</div>
  if (!user) return <LoginScreen login={login} />
  if (user.must_change_password) return <ChangePasswordScreen onDone={refresh} onLogout={logout} />

  return (
    <div className="app-shell">
      <Sidebar
        active={active}
        onNavigate={navigate}
        newOperationOpen={newOpOpen}
        onNewOperation={(el) => {
          if (el) setOriginY(el.getBoundingClientRect().top + el.getBoundingClientRect().height / 2)
          setNewOpOpen((v) => !v)
        }}
      />
      <div className="app-main">
        <header className="app-topbar">
          <input
            ref={searchRef} className="app-search" placeholder="بحث ذكي... ( / )"
            value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); runSearch() } }}
          />
          <NotificationsBell />
          <div className="user-chip">
            <div className="user-chip-avatar">{user.full_name.slice(0, 1)}</div>
            <div>
              <div style={{ fontSize: 'var(--fs-sm)', fontWeight: 600 }}>{user.full_name}</div>
              <div style={{ fontSize: 'var(--fs-2xs)', color: 'var(--text-muted)' }}>{user.role === 'ADMIN' ? 'مدير' : 'محاسب'}</div>
            </div>
            <button type="button" className="btn-text" onClick={() => void logout()}>خروج</button>
          </div>
        </header>
        <main
          key={transitionKey}
          className="app-content screen-enter"
          style={{ ['--origin-y' as string]: `${originY}px` }}
        >
          {active === 'journal' ? (
            <JournalScreen
              currentUserRole={user.role} canCreateClient={user.permissions.includes('CREATE_CLIENT')} requestedOpType={requestedOpType}
              onRequestedOpTypeConsumed={() => setRequestedOpType(null)}
            />
          ) : active === 'clients' ? (
            <ClientsScreen currentUserRole={user.role} />
          ) : active === 'dashboard' ? (
            <DashboardScreen />
          ) : active === 'position' ? (
            <LiquidityScreen />
          ) : active === 'accounts' ? (
            <AccountsScreen />
          ) : active === 'reports' ? (
            <ReportsScreen />
          ) : active === 'reconcile' ? (
            <ReconciliationScreen />
          ) : active === 'settings' ? (
            <SettingsScreen currentUserRole={user.role} />
          ) : (
            <Placeholder id={active} />
          )}
        </main>
      </div>
      {newOpOpen && (
        <NewOperationPanel
          onClose={() => setNewOpOpen(false)}
          onSelect={(opType) => {
            setRequestedOpType(opType)
            setActive('journal')
            setTransitionKey((k) => k + 1)
            setNewOpOpen(false)
          }}
        />
      )}
      {searchOpen && (
        <SearchResultsPanel
          chips={searchChips}
          onRemoveChip={(id) => setSearchChips((chips) => chips.filter((c) => c.id !== id))}
          onClose={() => setSearchOpen(false)}
          currentUserRole={user.role}
        />
      )}
    </div>
  )
}
