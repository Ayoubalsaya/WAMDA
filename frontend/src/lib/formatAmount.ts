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
