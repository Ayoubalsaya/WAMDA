const SYMBOLS: Record<string, string> = { LYD: 'د.ل', USD: '$', CNY: '¥' }
const CLASS: Record<string, string> = { LYD: 'badge-lyd', USD: 'badge-usd', CNY: 'badge-cny' }

// عملة رابعة فأكثر: لا رمز مخصص ولا لون مخصص بعد — رمادي محايد بدل
// إعادة استخدام لون الدولار (كان يُوهِم بأنها دولار).
export function CurrencyBadge({ code }: { code: string }) {
  return <span className={`badge ${CLASS[code] ?? 'badge-other'}`}>{SYMBOLS[code] ?? code} {code}</span>
}
