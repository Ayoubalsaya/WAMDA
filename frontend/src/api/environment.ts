// بيئة التشغيل (إنتاج/تطوير) واسم كوكي CSRF لها — تُحمَّل مرة واحدة قبل رسم الواجهة (main.tsx / portal-main.tsx).
// الكوكيز لا تفصل المنافذ: الإنتاج يستخدم أسماء بلاحقة wamda_prod_ فلا تتصادم جلسته مع جلسة التطوير على 127.0.0.1.
export type AppEnvironment = 'production' | 'local'

export interface EnvironmentInfo {
  environment: AppEnvironment
  csrfCookieName: string
}

let current: EnvironmentInfo = { environment: 'local', csrfCookieName: 'wamda_csrf' }

export function getEnvironment(): EnvironmentInfo {
  return current
}

const TITLE_PREFIX: Record<AppEnvironment, string> = { production: '[إنتاج] ', local: '[تطوير] ' }

export async function loadEnvironment(): Promise<EnvironmentInfo> {
  try {
    const res = await fetch('/environment', { credentials: 'include' })
    if (res.ok) {
      const d = (await res.json()) as { environment?: string; csrf_cookie_name?: string }
      current = {
        environment: d.environment === 'production' ? 'production' : 'local',
        csrfCookieName: typeof d.csrf_cookie_name === 'string' && d.csrf_cookie_name ? d.csrf_cookie_name : 'wamda_csrf',
      }
    }
  } catch {
    // الخادم غير متاح: تبقى القيم الافتراضية؛ أول طلب سيُظهر خطأ الاتصال المعتاد
  }
  document.title = TITLE_PREFIX[current.environment] + document.title.replace(/^\[(إنتاج|تطوير)\]\s*/, '')
  return current
}
