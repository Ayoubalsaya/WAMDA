import {
  LayoutDashboard, BookOpen, Users, Scale, Plus, Wallet, BarChart3, GitCompare, Settings,
} from 'lucide-react'
import { SegmentedTabs } from './SegmentedTabs'
import './Sidebar.css'

export type ScreenId =
  | 'dashboard' | 'journal' | 'clients' | 'position' | 'accounts' | 'reports' | 'reconcile' | 'settings'

const TOP_ITEMS: { id: ScreenId; label: string; icon: typeof LayoutDashboard; shortcut: string }[] = [
  { id: 'dashboard', label: 'لوحة التحكم', icon: LayoutDashboard, shortcut: 'Alt+1' },
  { id: 'journal', label: 'دفتر اليومية', icon: BookOpen, shortcut: 'Alt+2' },
  { id: 'clients', label: 'العملاء', icon: Users, shortcut: 'Alt+3' },
  { id: 'position', label: 'مركز السيولة', icon: Scale, shortcut: 'Alt+4' },
]

const BOTTOM_ITEMS: { id: ScreenId; label: string; icon: typeof LayoutDashboard; shortcut: string }[] = [
  { id: 'accounts', label: 'الحسابات', icon: Wallet, shortcut: 'Alt+5' },
  { id: 'reports', label: 'التقارير', icon: BarChart3, shortcut: 'Alt+6' },
  { id: 'reconcile', label: 'المطابقة', icon: GitCompare, shortcut: 'Alt+7' },
  { id: 'settings', label: 'الإعدادات', icon: Settings, shortcut: 'Alt+8' },
]

interface SidebarProps {
  active: ScreenId
  onNavigate: (id: ScreenId, originEl: HTMLElement | null) => void
  onNewOperation: (originEl: HTMLElement | null) => void
  newOperationOpen: boolean
}

// أيقونة فقط (rail بلا تسمية نصية) + تلميح hover يحمل الاسم والاختصار.
function toRailItems(metas: typeof TOP_ITEMS) {
  return metas.map((m) => ({
    id: m.id, label: '', icon: <m.icon size={21} strokeWidth={1.9} />, title: `${m.label} (${m.shortcut})`,
  }))
}

export function Sidebar({ active, onNavigate, onNewOperation, newOperationOpen }: SidebarProps) {
  function handleChange(id: ScreenId, el?: HTMLButtonElement) {
    onNavigate(id, el ?? null)
  }

  return (
    <nav className="sidebar" aria-label="التنقل الرئيسي">
      <SegmentedTabs
        variant="rail" ariaLabel="التنقل الأساسي"
        value={TOP_ITEMS.some((i) => i.id === active) ? active : ('' as ScreenId)}
        onChange={handleChange} items={toRailItems(TOP_ITEMS)}
      />

      <button
        type="button"
        className={`sidebar-center-btn${newOperationOpen ? ' is-open' : ''}`}
        title="عملية جديدة (Ctrl+N)"
        onClick={(e) => onNewOperation(e.currentTarget)}
      >
        <Plus size={24} strokeWidth={2.4} />
        <span className="center-btn-label">عملية جديدة</span>
      </button>

      <SegmentedTabs
        variant="rail" ariaLabel="تنقّل إضافي"
        value={BOTTOM_ITEMS.some((i) => i.id === active) ? active : ('' as ScreenId)}
        onChange={handleChange} items={toRailItems(BOTTOM_ITEMS)}
      />
    </nav>
  )
}
