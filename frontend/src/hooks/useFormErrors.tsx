import { useCallback, useRef, useState, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import { FieldErrorPortals, type PlacedError } from '../components/FieldErrorPortals'
import { placeFieldErrors } from '../lib/apiErrors'

// خطأ نموذج عام لكل شاشة غير دفتر اليومية (٢٠٢٦-١٠-٠٢، ملاحظة مالك): أخطاء التحقق (٤٢٢)
// بالعربية **تحت الحقل نفسه** باسمه كما يظهر في الشاشة، والباقي (خطأ غير تحقق، حقل بلا
// تسمية ظاهرة، مستوى الطلب) نصاً عاماً. الاستعمال:
//
//   const { ref, error, setError, report, portals } = useFormErrors({ name_ar: 'الاسم' })
//   <form ref={ref}> … {error && <div className="alert alert-critical">{error}</div>} {portals} </form>
//   catch (err) { report(err, 'تعذّر الحفظ') }       // بدل setError(err instanceof ApiError ? …)
//
// يُمسَح الخطأ تلقائياً بأول إدخال/تغيير داخل النموذج (لا خطأ قديم بجوار حقل مُصحَّح).
export type FormLabels = Record<string, string> | ((key: string, serverLabel: string | null) => string)

export function useFormErrors(labels: FormLabels = {}): {
  ref: (el: HTMLElement | null) => void
  error: string | null
  setError: (message: string | null) => void
  report: (err: unknown, fallback: string) => void
  portals: ReactNode
} {
  const rootEl = useRef<HTMLElement | null>(null)
  const detach = useRef<(() => void) | null>(null)
  const labelsRef = useRef<FormLabels>(labels)
  const [state, setState] = useState<{ placed: PlacedError[]; general: string | null }>({ placed: [], general: null })

  const ref = useCallback((el: HTMLElement | null) => {
    detach.current?.()
    detach.current = null
    rootEl.current = el
    if (!el) return
    const clear = () => setState((s) => (s.placed.length || s.general ? { placed: [], general: null } : s))
    el.addEventListener('input', clear)
    el.addEventListener('change', clear)
    detach.current = () => {
      el.removeEventListener('input', clear)
      el.removeEventListener('change', clear)
    }
  }, [])

  const setError = useCallback((message: string | null) => setState({ placed: [], general: message }), [])

  const report = useCallback((err: unknown, fallback: string) => {
    if (err instanceof ApiError && err.status === 422 && err.fieldErrors.length > 0) {
      const lab = labelsRef.current
      const { placed, general } = placeFieldErrors(err.fieldErrors, (key, server) => ({
        name: typeof lab === 'function' ? lab(key, server) : (lab[key] ?? server ?? 'الحقل'),
      }))
      setState({ placed, general: general.length ? general.join('؛ ') : null })
    } else {
      setState({ placed: [], general: err instanceof ApiError ? err.message : fallback })
    }
  }, [])

  labelsRef.current = labels
  return {
    ref, error: state.general, setError, report,
    portals: <FieldErrorPortals rootRef={rootEl} errors={state.placed} />,
  }
}
