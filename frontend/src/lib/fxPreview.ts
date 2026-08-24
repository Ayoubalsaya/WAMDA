// معاينة فورية في المتصفح فقط (decimal.js) — السيرفر يعيد الحساب دائماً
// ويرفض أي اختلاف يتجاوز خانة التقريب (القاعدة الإلزامية في مواصفة
// التصميم). يطابق app/engine/fx.py + app/engine/rounding.py حسابياً،
// لكنه ليس مصدر الحقيقة.

import Decimal from 'decimal.js'

export const PIVOT_CODE = 'USD'

// §١-٤: دولار → ثانوية = ضرب · ثانوية → دولار = قسمة
export function convertPreview(amount: string, rate: string, fromCurrency: string): Decimal {
  const a = new Decimal(amount || 0)
  const r = new Decimal(rate || 0)
  if (r.isZero()) return new Decimal(0)
  return fromCurrency === PIVOT_CODE ? a.times(r) : a.dividedBy(r)
}

// §٢-٥: مصفوفة التقريب المركزية
export function roundGivenToClient(value: Decimal, decimals: number): Decimal {
  return value.toDecimalPlaces(decimals, Decimal.ROUND_DOWN)
}
export function roundCollectedFromClient(value: Decimal, decimals: number): Decimal {
  return value.toDecimalPlaces(decimals, Decimal.ROUND_UP)
}
export function roundInternal(value: Decimal, decimals: number): Decimal {
  return value.toDecimalPlaces(decimals, Decimal.ROUND_HALF_UP)
}
