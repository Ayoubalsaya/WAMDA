import { useEffect, useRef, useState } from 'react'
import { AlertCircle, AlertTriangle, Bell, Info } from 'lucide-react'
import { api } from '../api/client'
import type { AlertRow, DashboardSummary } from '../api/types'

// د-٢: الجرس كان بلا أي معالج أحداث إطلاقاً — نفس صنف علّة اختصارات
// لوحة المفاتيح المتكرر مرتين سابقاً (المرحلتان ٥+٦). يعيد استخدام
// alerts من /dashboard/summary القائمة أصلاً (STAFF — كلا الدورين) بلا
// أي منطق تنبيه جديد مكرَّر.

const SEVERITY_ICON: Record<string, typeof AlertTriangle> = { critical: AlertCircle, warning: AlertTriangle, info: Info }
const SEVERITY_CLASS: Record<string, string> = { critical: 'alert-critical', warning: 'alert-warning', info: 'alert-info' }

export function NotificationsBell() {
  const [open, setOpen] = useState(false)
  const [alerts, setAlerts] = useState<AlertRow[] | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  async function load(background = false) {
    try {
      const data = background
        ? await api.getBackground<DashboardSummary>('/dashboard/summary')
        : await api.get<DashboardSummary>('/dashboard/summary')
      setAlerts(data.alerts)
    } catch {
      // 401 يعالجه حدث انتهاء الجلسة العام؛ غيره (انقطاع شبكة) لا يُسقط الواجهة
    }
  }

  useEffect(() => {
    void load()
    // الاستعلام الدوري آلي: لا يُحتسب نشاطاً (وإلا لم تنتهِ مهلة الخمول أبداً بوجود الصفحة مفتوحة)
    const timer = window.setInterval(() => void load(true), 60_000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!open) return
    function onOutside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    function onEscape(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    document.addEventListener('keydown', onEscape)
    return () => {
      document.removeEventListener('mousedown', onOutside)
      document.removeEventListener('keydown', onEscape)
    }
  }, [open])

  const list = alerts ?? []
  const hasCritical = list.some((a) => a.severity === 'critical')

  return (
    <div className="notif-bell-root" ref={rootRef}>
      <button
        type="button" className="btn btn-muted notif-bell-btn" aria-label="التنبيهات"
        aria-expanded={open} onClick={() => setOpen((v) => !v)}
      >
        <Bell size={18} strokeWidth={1.9} />
        {list.length > 0 && (
          <span className={`notif-dot${hasCritical ? ' notif-dot-critical' : ''}`}>{list.length > 9 ? '9+' : list.length}</span>
        )}
      </button>
      {open && (
        <div className="notif-dropdown card" role="dialog" aria-label="قائمة التنبيهات">
          <div className="card-title" style={{ marginBottom: 10 }}>التنبيهات</div>
          {alerts === null && <p className="text-muted" style={{ fontSize: 'var(--fs-sm)' }}>...جارٍ التحميل</p>}
          {alerts !== null && list.length === 0 && <p className="text-muted" style={{ fontSize: 'var(--fs-sm)' }}>لا تنبيهات حالياً</p>}
          {list.length > 0 && (
            <div className="alerts-list">
              {list.map((a, i) => {
                const Icon = SEVERITY_ICON[a.severity] ?? Info
                return (
                  <div key={i} className={`alert ${SEVERITY_CLASS[a.severity] ?? 'alert-info'}`}>
                    <Icon size={16} strokeWidth={1.9} />
                    <span style={{ fontSize: 'var(--fs-sm)' }}>{a.message_ar}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
