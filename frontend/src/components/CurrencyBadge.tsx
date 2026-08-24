const SYMBOLS: Record<string, string> = { LYD: 'د.ل', USD: '$', CNY: '¥' }
const CLASS: Record<string, string> = { LYD: 'badge-lyd', USD: 'badge-usd', CNY: 'badge-cny' }

export function CurrencyBadge({ code }: { code: string }) {
  return <span className={`badge ${CLASS[code] ?? 'badge-usd'}`}>{SYMBOLS[code] ?? code} {code}</span>
}
