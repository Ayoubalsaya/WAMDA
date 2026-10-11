import { getEnvironment } from '../api/environment'

// علامة البيئة: شريط علوي رفيع + شارة صغيرة في الزاوية. `position: fixed` و`pointer-events: none` — لا تُزيح التخطيط
// ولا تعترض نقراً. الإنتاج أحمر («بيانات حقيقية»)، التطوير كهرماني («بيانات تجريبية»).
// البوابة (عملاء): لا تُعرَض في الإنتاج (hideInProduction) — العلامة لموظفي ومطوّري النظام لا للعميل.
export function EnvBadge({ hideInProduction = false }: { hideInProduction?: boolean }) {
  const { environment } = getEnvironment()
  const isProd = environment === 'production'
  if (isProd && hideInProduction) return null
  const color = isProd ? '#b3261e' : '#b26a00'
  const label = isProd ? 'الإنتاج — بيانات حقيقية' : 'تطوير — بيانات تجريبية'
  return (
    <div aria-hidden="true" data-testid="env-badge" data-env={environment}>
      <div
        style={{
          position: 'fixed', top: 0, left: 0, right: 0, height: 4, background: color,
          zIndex: 2147483000, pointerEvents: 'none',
        }}
      />
      <div
        style={{
          position: 'fixed', bottom: 6, insetInlineStart: 6, background: color, color: '#fff',
          fontSize: 11, fontWeight: 700, lineHeight: 1, padding: '4px 8px', borderRadius: 999,
          zIndex: 2147483000, pointerEvents: 'none', opacity: 0.92, letterSpacing: 0.2,
        }}
      >
        {label}
      </div>
    </div>
  )
}
