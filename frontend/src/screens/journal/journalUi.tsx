import type { ReactNode } from 'react'
import { ChevronDown, X } from 'lucide-react'
import { SegmentedTabs } from '../../components/SegmentedTabs'

// مفردات تصميم دفتر اليومية (docs/design/journal-redesign-plan.md) كمكوّنات
// عرض صرفة — لا منطق ولا حالة هنا؛ القيم كلها تأتي من الشاشة (الأنماط في
// journal-design.css، متغيّرات tokens.css فقط).

// select-wrap: غلاف يضع سهم القائمة المنسدلة الموحَّد فوق <select> الأصلي —
// العنصر نفسه يبقى `<select>` حقيقياً (لوحة المفاتيح والوصولية كما هي).
export function SelectWrap({ children }: { children: ReactNode }) {
  return (
    <div className="select-wrap">
      {children}
      <ChevronDown className="select-caret" size={16} strokeWidth={2} aria-hidden="true" />
    </div>
  )
}

export type GuideTone = 'info' | 'warning' | 'critical' | 'success'

// form-guide: شريط جانبي ملوّن + خلفية فاتحة — للتلميحات والتحذيرات وأخطاء
// النموذج. `children` قد يحوي حقلاً وأزراراً (تجاوز الرصيد السالب/القيد الرجعي).
export function FormGuide({
  tone = 'info', title, children, onDismiss,
}: { tone?: GuideTone; title?: string; children?: ReactNode; onDismiss?: () => void }) {
  return (
    <div className={`form-guide tone-${tone}`} role={tone === 'critical' ? 'alert' : undefined}>
      <span className="guide-line" aria-hidden="true" />
      <div className="guide-body">
        {title && <strong>{title}</strong>}
        {children != null && <div className="guide-text">{children}</div>}
      </div>
      {onDismiss && (
        <button type="button" className="dismiss-note" aria-label="إخفاء" onClick={onDismiss}>
          <X size={16} strokeWidth={2} />
        </button>
      )}
    </div>
  )
}

// amount-stage: المبلغ الأساسي يُرفع إلى مركز الاهتمام. الحقل نفسه `.field`
// عادي (label + input) كي تبقى تسمية الحقل وسلوكه كما كانا تماماً.
export function AmountStage({
  label, value, onChange, currencyCode, id,
}: { label: string; value: string; onChange: (v: string) => void; currencyCode?: string; id?: string }) {
  return (
    <div className="field amount-stage">
      <label className="field-label" htmlFor={id}>{label}</label>
      <div className="amount-entry">
        <input id={id} className="num" inputMode="decimal" placeholder="0.000" value={value} onChange={(e) => onChange(e.target.value)} />
        {currencyCode && <span className="amount-currency num">{currencyCode}</span>}
      </div>
    </div>
  )
}

// pill-tab: تبويبات فرعية صغيرة (نطاق الصرافة · مصدر تحصيل العمولة) —
// غلاف رقيق فوق SegmentedTabs المشتركة (الكبسولة النابضة، طلب مالك
// ٢٠٢٦-٠٩-٢٧) بمظهر "pill". لا منطق حركة هنا — كله في المكوّن المشترك.
export function PillTabs<T extends string>({
  value, options, onChange, label,
}: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return <SegmentedTabs variant="pill" ariaLabel={label} value={value} onChange={onChange} items={options} />
}
