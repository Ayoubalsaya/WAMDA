// البحث الذكي (§٧-١٠) — يُحلَّل النص المكتوب إلى رقائق مُهيكَلة قابلة
// للإزالة فرداً فرداً، ثم تُرسَل كمُدخَلات صريحة لـ`GET /search` — لا
// إعادة تحليل النص خادمياً (تفادياً لتناقض منطقَي تحليل).

export interface SearchChip {
  id: string
  label: string
  kind: 'entryNo' | 'chainRef' | 'minAmount' | 'currency' | 'dateRange' | 'operationType' | 'username' | 'text'
  value: string
}

export interface SearchParams {
  q?: string
  entry_no?: string
  chain_ref?: string
  min_amount?: string
  currency?: string
  date_from?: string
  date_to?: string
  operation_type?: string
  username?: string
}

// احتياطي فقط لحين توفر القائمة الحية من `/reference/currencies` — أي
// عملة تُضاف من شاشة الإعدادات يجب أن تُمرَّر عبر `knownCurrencies` في
// `parseSearchQuery` كي تُصنَّف رقاقة بحث بدل نص حر.
const FALLBACK_CURRENCIES = new Set(['LYD', 'USD', 'CNY'])

const OP_TYPE_BY_ARABIC: Record<string, string> = {
  'قبض': 'RECEIPT', 'صرف': 'PAYMENT', 'صرافة': 'EXCHANGE', 'تحويل بعمولة': 'CASH_TRANSFER',
  'نقل داخلي': 'LOCAL_MOVE', 'سويفت خروج': 'SWIFT_OUT', 'سويفت وصول': 'SWIFT_IN',
  'سويفت مرتجع': 'SWIFT_RETURN', 'إرسال': 'REMIT_OUT', 'إرسال خارجي': 'REMIT_OUT', 'إرسال لمستفيد': 'REMIT_OUT',
  'مصروف': 'EXPENSE', 'رصيد افتتاحي': 'OPENING', 'تسوية': 'ADJUSTMENT',
}

function tokenClassify(token: string, knownCurrencies: Set<string>): SearchChip | null {
  if (!token) return null
  if (/^WMD-/i.test(token) || /^\d{4}-WMD-/i.test(token)) {
    return { id: `entryNo-${token}`, label: token, kind: 'entryNo', value: token }
  }
  if (/^CHN-/i.test(token)) {
    return { id: `chainRef-${token}`, label: token, kind: 'chainRef', value: token }
  }
  if (/^>\s?\d+(\.\d+)?$/.test(token)) {
    const value = token.replace('>', '').trim()
    return { id: `minAmount-${value}`, label: `أكبر من ${value}`, kind: 'minAmount', value }
  }
  if (knownCurrencies.has(token.toUpperCase())) {
    const code = token.toUpperCase()
    return { id: `currency-${code}`, label: code, kind: 'currency', value: code }
  }
  const dateRangeMatch = token.match(/^(\d{4}-\d{2}(-\d{2})?)\.\.(\d{4}-\d{2}(-\d{2})?)$/)
  if (dateRangeMatch) {
    const from = dateRangeMatch[1].length === 7 ? `${dateRangeMatch[1]}-01` : dateRangeMatch[1]
    const to = dateRangeMatch[3].length === 7 ? `${dateRangeMatch[3]}-28` : dateRangeMatch[3]
    return { id: `dateRange-${token}`, label: token, kind: 'dateRange', value: `${from}..${to}` }
  }
  if (token.startsWith('@') && token.length > 1) {
    const value = token.slice(1)
    return { id: `username-${value}`, label: token, kind: 'username', value }
  }
  if (OP_TYPE_BY_ARABIC[token]) {
    return { id: `opType-${token}`, label: token, kind: 'operationType', value: OP_TYPE_BY_ARABIC[token] }
  }
  return { id: `text-${token}`, label: token, kind: 'text', value: token }
}

// يُحلِّل السطر كاملاً أولاً كعبارات نوع عملية معروفة متعددة الكلمات
// (مثل "تحويل بعمولة")، ثم يُقسِّم الباقي بمسافات مفردة.
export function parseSearchQuery(raw: string, knownCurrencies?: Iterable<string>): SearchChip[] {
  const currencies = knownCurrencies ? new Set([...knownCurrencies].map((c) => c.toUpperCase())) : FALLBACK_CURRENCIES
  let remaining = raw.trim()
  const chips: SearchChip[] = []
  for (const phrase of Object.keys(OP_TYPE_BY_ARABIC).sort((a, b) => b.length - a.length)) {
    if (remaining.includes(phrase)) {
      chips.push({ id: `opType-${phrase}`, label: phrase, kind: 'operationType', value: OP_TYPE_BY_ARABIC[phrase] })
      remaining = remaining.replace(phrase, ' ').trim()
    }
  }
  const tokens = remaining.split(/\s+/).filter(Boolean)
  for (const token of tokens) {
    const chip = tokenClassify(token, currencies)
    if (chip) chips.push(chip)
  }
  return chips
}

export function chipsToParams(chips: SearchChip[]): SearchParams {
  const params: SearchParams = {}
  const textParts: string[] = []
  for (const chip of chips) {
    switch (chip.kind) {
      case 'entryNo': params.entry_no = chip.value; break
      case 'chainRef': params.chain_ref = chip.value; break
      case 'minAmount': params.min_amount = chip.value; break
      case 'currency': params.currency = chip.value; break
      case 'operationType': params.operation_type = chip.value; break
      case 'username': params.username = chip.value; break
      case 'dateRange': {
        const [from, to] = chip.value.split('..')
        params.date_from = from
        params.date_to = to
        break
      }
      case 'text': textParts.push(chip.value); break
    }
  }
  if (textParts.length > 0) params.q = textParts.join(' ')
  return params
}
