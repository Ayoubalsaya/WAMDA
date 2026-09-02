import { useState } from 'react'
import { Copy, Check } from 'lucide-react'

type CopyState = 'idle' | 'copying' | 'copied' | 'downloaded' | 'error'

interface BalanceCardCopyButtonProps {
  src: string
  className?: string
}

// §و-٢: نسخ مباشر لبطاقة الرصيد إلى الحافظة — لصقة واحدة في واتساب لا
// فتح/حفظ/رفع. يعمل من حزمتي الموظف والبوابة كليهما (مصدر الصورة src فقط يختلف).
export function BalanceCardCopyButton({ src, className }: BalanceCardCopyButtonProps) {
  const [state, setState] = useState<CopyState>('idle')

  async function copyCard() {
    setState('copying')
    try {
      const res = await fetch(src, { credentials: 'include' })
      if (!res.ok) throw new Error('fetch failed')
      const blob = await res.blob()
      try {
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
        setState('copied')
      } catch {
        // سقوط تلقائي: المتصفح لا يدعم ClipboardItem للصور أو رُفض الإذن — تنزيل بدلاً من ذلك
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = 'balance-card.png'
        document.body.appendChild(a)
        a.click()
        a.remove()
        URL.revokeObjectURL(url)
        setState('downloaded')
      }
    } catch {
      setState('error')
    } finally {
      setTimeout(() => setState('idle'), 2500)
    }
  }

  const label = state === 'copying' ? '...جارٍ النسخ' : state === 'copied' ? 'تم النسخ ✓' : state === 'downloaded' ? 'نُزِّلت الصورة' : state === 'error' ? 'تعذّر النسخ' : 'نسخ البطاقة كصورة'

  return (
    <button type="button" className={className ?? 'btn btn-secondary btn-sm'} onClick={() => void copyCard()} disabled={state === 'copying'}>
      {state === 'copied' ? <Check size={14} strokeWidth={2} /> : <Copy size={14} strokeWidth={1.9} />}
      {label}
    </button>
  )
}
