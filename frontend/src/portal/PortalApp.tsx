import { usePortalAuth } from './usePortalAuth'
import { PortalLoginScreen } from './PortalLoginScreen'
import { PortalChangePasswordScreen } from './PortalChangePasswordScreen'
import { PortalHomeScreen } from './PortalHomeScreen'

export function PortalApp() {
  const { me, checking, login, logout, refresh } = usePortalAuth()

  if (checking) return <div className="app-loading">...جارٍ التحقق من الجلسة</div>
  if (!me) return <PortalLoginScreen login={login} />
  // §٧-٦/اختبار القبول ٤٢: لا شيء آخر يُعرَض قبل تغيير كلمة المرور —
  // بوابياً هنا (لا اعتماداً على ٤٠٣ الخادم وحده كما في واجهة الموظف
  // التي لم تُبنَ لها شاشة إجبار مماثلة بعد، انظر ديون تقنية PROGRESS.md).
  if (me.must_change_password) {
    return <PortalChangePasswordScreen onDone={refresh} onLogout={logout} />
  }
  return <PortalHomeScreen me={me} onLogout={logout} />
}
