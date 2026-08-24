import { useRef } from 'react'
import {
  LayoutDashboard, BookOpen, Users, Scale, Plus, Wallet, BarChart3, GitCompare, Settings,
} from 'lucide-react'
import './Sidebar.css'

export type ScreenId =
  | 'dashboard' | 'journal' | 'clients' | 'position' | 'accounts' | 'reports' | 'reconcile' | 'settings'

const TOP_ITEMS: { id: ScreenId; label: string; Icon: typeof LayoutDashboard; shortcut: string }[] = [
  { id: 'dashboard', label: 'لوحة التحكم', Icon: LayoutDashboard, shortcut: 'Alt+1' },
  { id: 'journal', label: 'دفتر اليومية', Icon: BookOpen, shortcut: 'Alt+2' },
  { id: 'clients', label: 'العملاء', Icon: Users, shortcut: 'Alt+3' },
  { id: 'position', label: 'مركز السيولة', Icon: Scale, shortcut: 'Alt+4' },
]

const BOTTOM_ITEMS: { id: ScreenId; label: string; Icon: typeof LayoutDashboard; shortcut: string }[] = [
  { id: 'accounts', label: 'الحسابات', Icon: Wallet, shortcut: 'Alt+5' },
  { id: 'reports', label: 'التقارير', Icon: BarChart3, shortcut: 'Alt+6' },
  { id: 'reconcile', label: 'المطابقة', Icon: GitCompare, shortcut: 'Alt+7' },
  { id: 'settings', label: 'الإعدادات', Icon: Settings, shortcut: 'Alt+8' },
]

interface SidebarProps {
  active: ScreenId
  onNavigate: (id: ScreenId, originEl: HTMLElement | null) => void
  onNewOperation: (originEl: HTMLElement | null) => void
  newOperationOpen: boolean
}

function NavButton({
  item, active, onNavigate,
}: {
  item: { id: ScreenId; label: string; Icon: typeof LayoutDashboard; shortcut: string }
  active: boolean
  onNavigate: (id: ScreenId, originEl: HTMLElement | null) => void
}) {
  const ref = useRef<HTMLButtonElement>(null)
  const { Icon } = item
  return (
    <button
      ref={ref}
      type="button"
      className={`sidebar-icon-btn${active ? ' is-active' : ''}`}
      title={`${item.label} (${item.shortcut})`}
      aria-current={active}
      onClick={() => onNavigate(item.id, ref.current)}
    >
      {active && <span className="active-pill" aria-hidden="true" />}
      <Icon size={21} strokeWidth={1.9} />
    </button>
  )
}

export function Sidebar({ active, onNavigate, onNewOperation, newOperationOpen }: SidebarProps) {
  const centerRef = useRef<HTMLButtonElement>(null)
  return (
    <nav className="sidebar" aria-label="التنقل الرئيسي">
      <div className="sidebar-group">
        {TOP_ITEMS.map((item) => (
          <NavButton key={item.id} item={item} active={active === item.id} onNavigate={onNavigate} />
        ))}
      </div>

      <button
        ref={centerRef}
        type="button"
        className={`sidebar-center-btn${newOperationOpen ? ' is-open' : ''}`}
        title="عملية جديدة (Ctrl+N)"
        onClick={() => onNewOperation(centerRef.current)}
      >
        <Plus size={24} strokeWidth={2.4} />
        <span className="center-btn-label">عملية جديدة</span>
      </button>

      <div className="sidebar-group">
        {BOTTOM_ITEMS.map((item) => (
          <NavButton key={item.id} item={item} active={active === item.id} onNavigate={onNavigate} />
        ))}
      </div>
    </nav>
  )
}
