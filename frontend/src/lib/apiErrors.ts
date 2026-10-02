import type { FieldError } from '../api/client'
import type { PlacedError } from '../components/FieldErrorPortals'

// يحوّل أخطاء التحقق المترجمة من الخادم (ApiError.fieldErrors) إلى أخطاء موضوعة
// تحت الحقول بأسمائها **كما تظهر في الشاشة** (`labelFor` خاصة بكل نموذج) — انظر
// components/FieldErrorPortals.tsx. الأخطاء بلا حقل (مستوى الطلب) تعود نصوصاً عامة.
export interface FieldLabel { name: string; place?: string; nth?: 'first' | 'last' }
export type LabelFor = (key: string, serverLabel: string | null) => FieldLabel

export function placeFieldErrors(
  errors: FieldError[], labelFor: LabelFor, opts: { editMode?: boolean } = {},
): { placed: PlacedError[]; general: string[] } {
  const byKey = new Map<string, PlacedError>()
  const general: string[] = []
  for (const e of errors) {
    const loc = [...e.loc]
    if (opts.editMode && loc[0] === 'operation') loc.shift()
    else if (opts.editMode && loc[0] === 'reason') loc[0] = 'edit_reason'  // سبب التعديل ≠ سبب التسوية
    if (!e.field || loc.length === 0) {
      general.push(e.message)
      continue
    }
    const key = loc.join('.')
    const { name, place, nth } = labelFor(key, e.label)
    const existing = byKey.get(key)
    if (existing) existing.message = `${existing.message}؛ ${e.message}`
    else byKey.set(key, { key, name, place: place ?? name, message: e.message, nth })
  }
  return { placed: [...byKey.values()], general }
}
