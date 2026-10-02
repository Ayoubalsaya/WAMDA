import { useState } from 'react'
import { Copy, Printer } from 'lucide-react'
import './BackupCodesPanel.css'

// عرض الرموز الاحتياطية للمصادقة (٢٠٢٦-١٠-٠٣): تُعرض **مرة واحدة فقط** عند الإنشاء (أول إعداد للمصادقة · إعادة الإنشاء)،
// مع نسخ وطباعة، وتنبيه «لن تظهر مرة أخرى». المتابعة مشروطة بإقرار المستخدم أنه حفظها (إلزامي في أول دخول).
interface BackupCodesPanelProps {
  codes: string[]
  onAcknowledged: () => void
  title?: string
  continueLabel?: string
}

export function BackupCodesPanel({ codes, onAcknowledged, title = 'الرموز الاحتياطية', continueLabel = 'متابعة' }: BackupCodesPanelProps) {
  const [saved, setSaved] = useState(false)
  const [copied, setCopied] = useState(false)

  async function copyAll() {
    try {
      await navigator.clipboard.writeText(codes.join('\n'))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // الحافظة غير متاحة (سياق غير آمن) — الطباعة والنسخ اليدوي بديلان
    }
  }

  return (
    <section className="backup-codes" aria-label={title} data-testid="backup-codes-panel">
      <h3 className="card-title">{title}</h3>
      <div className="alert alert-warning" role="alert">
        <strong>لن تظهر هذه الرموز مرة أخرى.</strong> احفظها الآن في مكان آمن. كل رمز يعمل <strong>مرة واحدة</strong> فقط بدل رمز تطبيق المصادقة
        (وكلمة المرور تبقى مطلوبة دائماً).
      </div>
      <ol className="backup-codes-grid backup-codes-print" data-testid="backup-codes-list">
        {codes.map((c) => <li key={c} className="num">{c}</li>)}
      </ol>
      <div className="backup-codes-actions">
        <button type="button" className="btn btn-secondary" onClick={() => void copyAll()}>
          <Copy size={16} strokeWidth={2} /> {copied ? 'نُسخت ✓' : 'نسخ الرموز'}
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => { document.body.classList.add('printing-backup-codes'); window.print(); document.body.classList.remove('printing-backup-codes') }}>
          <Printer size={16} strokeWidth={2} /> طباعة
        </button>
      </div>
      <label className="check-row backup-codes-ack">
        <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
        حفظتُ الرموز في مكان آمن
      </label>
      <button type="button" className="btn btn-primary btn-lg" style={{ width: '100%' }} disabled={!saved} onClick={onAcknowledged}>
        {continueLabel}
      </button>
    </section>
  )
}
