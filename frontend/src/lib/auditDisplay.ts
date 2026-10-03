import Decimal from 'decimal.js'
import type { Currency } from '../api/types'

// سجل التدقيق يخزّن المبالغ نصوصاً بست منازل خام («15000.000000»). للعرض: أي كائن فيه currency_code تُنسَّق مبالغه
// (debit/credit/amount/limit_amount/balance…) بخانات تلك العملة؛ ما سواه يبقى كما هو (لا تخمين لعملة غير مذكورة).
const AMOUNT_KEYS = new Set(['amount', 'limit_amount', 'debit', 'credit', 'balance', 'total_amount', 'fee_amount', 'profit_amount'])

export function displayAudit(value: unknown, currencies: Currency[]): unknown {
  if (Array.isArray(value)) return value.map((v) => displayAudit(v, currencies))
  if (value && typeof value === 'object') {
    const obj = value as Record<string, unknown>
    const ccy = typeof obj.currency_code === 'string' ? obj.currency_code : null
    const decimals = ccy ? currencies.find((c) => c.code === ccy)?.decimals : undefined
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(obj)) {
      if (decimals !== undefined && AMOUNT_KEYS.has(k) && typeof v === 'string' && /^-?\d+(\.\d+)?$/.test(v)) out[k] = new Decimal(v).toFixed(decimals)
      else out[k] = displayAudit(v, currencies)
    }
    return out
  }
  return value
}
