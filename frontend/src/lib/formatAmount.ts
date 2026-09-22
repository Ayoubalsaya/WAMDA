import Decimal from 'decimal.js'
import type { Currency } from '../api/types'

// أ-٥: كل مبلغ مالي يُعرض بعدد منازل عملته الفعلي لا بالدقة الخام التي
// يرسلها API دائماً بست منازل (Numeric(20,6))، بصرف النظر عن عملة السطر —
// نفس التنسيق المعتمد في ClientDetailView.tsx.
export function formatAmount(value: string, currencyCode: string, currencies: Currency[]): string {
  const decimals = currencies.find((c) => c.code === currencyCode)?.decimals ?? 2
  return new Decimal(value).toFixed(decimals)
}

// أسعار الصرف/التكلفة تُخزَّن بدقة Numeric(20,10) لأسباب محاسبية داخلية —
// لا علاقة لذلك بعدد المنازل المفيد للعرض البشري. يُزال الصفر الزائد فقط
// (Number بدل Decimal هنا يكفي: أسعار الصرف الواقعية لا تقترب من حدود
// دقة الأرقام العائمة في JS).
export function formatRate(value: string): string {
  return Number(value).toString()
}

export type BalanceTone = 'pos' | 'neg' | 'zero'

// ٢٠٢٦-٠٩-٢٢: عرض رصيد داخل قائمة اختيار حساب — إشارة ناقص + فواصل آلاف
// (خلاف formatAmount في بقية الشاشات عمداً: القائمة تُقرَأ سريعاً أثناء
// الاختيار، الفاصلة تُسهِّل تمييز الرقم دون عدّ الأصفار).
export function formatAccountBalance(
  value: string, currencyCode: string | null, currencies: Currency[]
): { text: string; tone: BalanceTone } {
  const decimals = currencies.find((c) => c.code === currencyCode)?.decimals ?? 2
  const d = new Decimal(value || '0')
  const tone: BalanceTone = d.isPositive() && !d.isZero() ? 'pos' : d.isNegative() ? 'neg' : 'zero'
  const [intPart, fracPart] = d.abs().toFixed(decimals).split('.')
  const withCommas = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const text = (tone === 'neg' ? '−' : '') + withCommas + (fracPart ? '.' + fracPart : '')
  return { text, tone }
}
