import Decimal from 'decimal.js'
import type { Currency, JournalLineOut } from '../api/types'
import { formatAmount } from './formatAmount'

// سطر قيد = أحد جانبين فقط (مدين أو دائن): الاتجاه يُستنتج بمقارنة عشرية (Decimal) لا بمقارنة نصية —
// الـAPI يُرسل «0.000000» بست منازل، والمقارنة النصية بـ'0'/'0.000' كانت تُخطئ دائماً فيظهر سطر الدائن «0.000000» (٢٠٢٦-١٠-٠٤).
export interface LineAmount {
  side: 'debit' | 'credit'
  label: 'مدين' | 'دائن'
  text: string  // المبلغ الفعلي للسطر بخانات عملته
}

export function lineAmount(line: Pick<JournalLineOut, 'debit' | 'credit' | 'currency_code'>, currencies: Currency[]): LineAmount {
  const isDebit = new Decimal(line.debit || '0').gt(0)
  const value = isDebit ? line.debit : line.credit
  return { side: isDebit ? 'debit' : 'credit', label: isDebit ? 'مدين' : 'دائن', text: formatAmount(value, line.currency_code, currencies) }
}
