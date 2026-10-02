import { useLayoutEffect, useState, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { FormGuide } from '../screens/journal/journalUi'

// أخطاء التحقق (٤٢٢) تحت الحقل نفسه (٢٠٢٦-١٠-٠٢، ملاحظة مالك): كل خطأ يأتي من
// الخادم بالعربية (`app/validation_errors.py`)؛ هذا المكوّن يضعه تحت الحقل الذي
// يحمل **الاسم الظاهر** نفسه في الشاشة (`.field` ← `label.field-label`) عبر
// بوابة React، بلا توصيل يدوي لكل حقل من عشرات الحقول. ما لا يجد له حقلاً ظاهراً
// (حقل في خطوة أخرى، زر اختيار، خطأ على مستوى الطلب) يُعرض في قائمة عامة أسفل
// النموذج — لا يضيع أي خطأ ولا يُعرض JSON خام أبداً.
export interface PlacedError {
  key: string
  name: string       // الاسم المعروض في الرسالة
  place: string      // نص تسمية الحقل الظاهرة التي يُوضَع تحتها (بلا الأقواس الأخيرة)
  message: string
  nth?: 'first' | 'last'
}

// «المبلغ (USD)» ← «المبلغ» · «ملاحظة (اختياري)» ← «ملاحظة»
export function normalizeLabel(text: string): string {
  return text.replace(/\s*[(（][^)）]*[)）]\s*$/, '').replace(/\s+/g, ' ').trim()
}

function findFieldEl(root: HTMLElement, e: PlacedError): HTMLElement | null {
  const want = normalizeLabel(e.place)
  const matches = Array.from(root.querySelectorAll<HTMLElement>('.field')).filter((el) => {
    const label = el.querySelector(':scope > label.field-label, :scope > .field-label')
    return !!label && normalizeLabel(label.textContent ?? '') === want
  })
  if (!matches.length) return null
  return e.nth === 'last' ? matches[matches.length - 1] : matches[0]
}

export function FieldErrorPortals({ rootRef, errors }: { rootRef: RefObject<HTMLElement | null>; errors: PlacedError[] }) {
  const [placement, setPlacement] = useState<{ placed: [PlacedError, HTMLElement][]; unplaced: PlacedError[] }>({ placed: [], unplaced: [] })

  // يُحسَب بعد كل تحديث للـDOM: الحقول تظهر/تختفي مع التبويب والخطوة
  useLayoutEffect(() => {
    const root = rootRef.current
    const placed: [PlacedError, HTMLElement][] = []
    const unplaced: PlacedError[] = []
    for (const e of errors) {
      const el = root ? findFieldEl(root, e) : null
      if (el) placed.push([e, el])
      else unplaced.push(e)
    }
    setPlacement((prev) => {
      const same = prev.placed.length === placed.length && prev.unplaced.length === unplaced.length
        && prev.placed.every(([pe, pel], i) => pe === placed[i][0] && pel === placed[i][1])
        && prev.unplaced.every((u, i) => u === unplaced[i])
      return same ? prev : { placed, unplaced }
    })
  })

  return (
    <>
      {placement.placed.map(([e, el]) =>
        createPortal(
          <span key={e.key} className="field-error" role="alert" data-field-error={e.key}>«{e.name}»: {e.message}</span>,
          el, e.key,
        ))}
      {placement.unplaced.length > 0 && (
        <FormGuide tone="critical" title="راجع البيانات المُدخَلة">
          {placement.unplaced.map((e) => <div key={e.key} data-field-error={e.key}>«{e.name}»: {e.message}</div>)}
        </FormGuide>
      )}
    </>
  )
}
