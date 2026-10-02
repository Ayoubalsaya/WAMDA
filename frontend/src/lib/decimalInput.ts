// تطبيع وفحص حقول الأرقام (مبالغ/أسعار) — قاعدة واحدة تضمن أن **القيمة
// المعروضة في الحقل هي بالضبط القيمة المُرسَلة** (٢٠٢٦-١٠-٠٢، ملاحظة مالك):
// الحقل مُتحكَّم به (value = الحالة)، فالمُرسَل = الحالة = المعروض بالتعريف؛
// هذا الملف يمنع فقط أن تصير الحالة قيمة لا يفهمها الخادم ولا المعاينة.
//
// ما يُحوَّل بلا فقد (لا تخمين): الأرقام العربية-الهندية/الفارسية ← لاتينية،
// الفاصلة العشرية العربية «٫» ← «.»، وتُحذف المسافات وعلامات الاتجاه
// (تأتي مع اللصق من واتساب/إكسل). **الفاصلة العادية «,»/«،» لا تُخمَّن**
// (٩,٠٥ كسر أم «١٠٠٠» آلاف؟) — تبقى في الحقل ويُعلَّم الحقل غير صالح برسالة.

import Decimal from 'decimal.js'

const ARABIC_INDIC = '٠١٢٣٤٥٦٧٨٩'
const EXTENDED_ARABIC_INDIC = '۰۱۲۳۴۵۶۷۸۹'
const INVISIBLE = /[\s ​-‏‪-‮⁦-⁩﻿]/

export function normalizeDecimalInput(raw: string): string {
  let out = ''
  for (const ch of raw) {
    const a = ARABIC_INDIC.indexOf(ch)
    if (a >= 0) { out += String(a); continue }
    const p = EXTENDED_ARABIC_INDIC.indexOf(ch)
    if (p >= 0) { out += String(p); continue }
    if (ch === '٫') { out += '.'; continue }
    if (INVISIBLE.test(ch)) continue
    out += ch
  }
  return out
}

const VALID_DECIMAL = /^(\d+\.?\d*|\.\d+)$/

// null = صالح (أو فارغ — الإلزام يفحصه الخادم/المنطق الخاص بكل نموذج)
export function decimalInputError(value: string): string | null {
  if (value === '' || VALID_DECIMAL.test(value)) return null
  if (/[,،٬]/.test(value)) return 'استخدم النقطة (.) للكسر العشري ولا تضع فواصل للآلاف'
  return 'أدخل رقماً فقط: أرقاماً ونقطة عشرية واحدة'
}

// تحليل آمن للمعاينة — لا يرمي أبداً (DecimalError كان يُسقط الواجهة كلها)
export function parseDecimalSafe(value: string): Decimal {
  if (decimalInputError(value) !== null) return new Decimal(0)
  try {
    return new Decimal(value || 0)
  } catch {
    return new Decimal(0)
  }
}
