import { usePortalAuth } from './usePortalAuth'
import { PortalLoginScreen } from './PortalLoginScreen'
import { PortalAcceptInviteScreen } from './PortalAcceptInviteScreen'
import { PortalHomeScreen } from './PortalHomeScreen'

// رابط الدعوة: {PUBLIC_BASE_URL}/static/app/portal.html#invite=TOKEN —
// الرمز بعد # عمداً (جزء العميل، لا يُرسَل للخادم في طلب تحميل الصفحة
// نفسها، فلا يظهر في أي سجل وصول).
function inviteTokenFromHash(): string | null {
  const match = window.location.hash.match(/^#invite=(.+)$/)
  return match ? decodeURIComponent(match[1]) : null
}

export function PortalApp() {
  const { me, checking, login, logout } = usePortalAuth()
  const inviteToken = inviteTokenFromHash()

  if (inviteToken) {
    return <PortalAcceptInviteScreen token={inviteToken} />
  }
  if (checking) return <div className="app-loading">...جارٍ التحقق من الجلسة</div>
  if (!me) return <PortalLoginScreen login={login} />
  return <PortalHomeScreen me={me} onLogout={logout} />
}
