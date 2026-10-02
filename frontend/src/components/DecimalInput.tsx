import type { InputHTMLAttributes } from 'react'
import { decimalInputError, normalizeDecimalInput } from '../lib/decimalInput'

// حقل رقم (مبلغ/سعر) مشترك — يستبدل كل `<input>` رقمي في النماذج. القيمة
// المخزَّنة = المعروضة = المُرسَلة؛ التطبيع (أرقام عربية ← لاتينية…) يجري
// عند الإدخال نفسه فيرى المستخدم ما سيُرسَل. انظر lib/decimalInput.ts.
type NativeProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type'>

export function DecimalInput({ value, onChange, ...rest }: NativeProps & { value: string; onChange: (v: string) => void }) {
  const invalid = decimalInputError(value) !== null
  return (
    <input
      inputMode="decimal" autoComplete="off" spellCheck={false}
      aria-invalid={invalid || undefined}
      {...rest}
      value={value}
      onChange={(e) => onChange(normalizeDecimalInput(e.target.value))}
    />
  )
}

// رسالة الحقل غير الصالح تحت الحقل — بالعربية، لا شيء إن كان صالحاً/فارغاً
export function DecimalError({ value }: { value: string }) {
  const message = decimalInputError(value)
  return message ? <span className="rate-hint field-error" role="alert">{message}</span> : null
}
