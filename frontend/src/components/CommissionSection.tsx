import { useMemo } from 'react'
import { AccountPicker, type AccountPickerSpec } from './AccountPicker'
import { useReferenceData } from '../hooks/useReferenceData'
import { AmountStage, PillTabs, SelectWrap } from '../screens/journal/journalUi'

// عمولة اختيارية (٢٠٢٦-١٠-٠٤): اتجاه · عملة مستقلة عن عملة العملية · مبلغ · حساب. تُستعمل في نموذج الصرافة وفي كل خطوة من المعالج وفي النقل الداخلي/تحويل الخزينة.
export interface CommissionState {
  open: boolean
  direction: 'IN' | 'OUT'  // IN نقبضها (إيراد) · OUT ندفعها (مصروف)
  currency: string
  amount: string
  source: 'COMPANY' | 'CLIENT'
  account: string
  location: string
}

// الاتجاه الافتراضي: نقبضها في الصرافة، وندفعها في نقل الخزينة (الحالة الغالبة هناك)
export const emptyCommission = (direction: 'IN' | 'OUT' = 'IN'): CommissionState => ({ open: false, direction, currency: '', amount: '', source: 'COMPANY', account: '', location: '' })

// حقول الطلب: تُرسَل فقط إن فُتح القسم وأُدخل مبلغ. نطاق الخزينة حساب شركة دائماً؛ نطاق العميل حساب شركة أو حساب العميل (موقع).
export function commissionToPayload(c: CommissionState, scope: 'CLIENT' | 'TREASURY'): Record<string, string | undefined> {
  if (!c.open || !c.amount) return {}
  const company = scope === 'TREASURY' || c.source === 'COMPANY'
  return {
    commission_direction: c.direction, commission_currency: c.currency, commission_amount: c.amount,
    commission_account_code: company ? c.account : undefined,
    commission_location_code: company ? undefined : c.location,
  }
}

// الإسقاط العكسي من جسم طلب محفوظ (فتح التعديل مملوءاً)
export function commissionFromRequest(r: Record<string, unknown>): CommissionState {
  if (!r.commission_amount) return emptyCommission()
  const byLocation = Boolean(r.commission_location_code)
  return {
    open: true, direction: r.commission_direction === 'OUT' ? 'OUT' : 'IN', currency: String(r.commission_currency ?? ''), amount: String(r.commission_amount),
    source: byLocation ? 'CLIENT' : 'COMPANY', account: byLocation ? '' : String(r.commission_account_code ?? ''), location: byLocation ? String(r.commission_location_code) : '',
  }
}

interface CommissionSectionProps {
  value: CommissionState
  onChange: (next: CommissionState) => void
  scope: 'CLIENT' | 'TREASURY'
  idPrefix?: string  // معرّف حقل المبلغ: `${idPrefix}-amount`
  testId?: string
}

export function CommissionSection({ value, onChange, scope, idPrefix = 'commission', testId = 'commission-section' }: CommissionSectionProps) {
  const { currencies, locationsForCurrency } = useReferenceData()
  const set = (patch: Partial<CommissionState>) => onChange({ ...value, ...patch })
  const spec: AccountPickerSpec | null = value.open && value.currency
    ? { mode: 'operation', operationType: 'EXCHANGE', field: 'commission', currencyCode: value.currency } : null
  const clientLocations = useMemo(() => locationsForCurrency(value.currency), [value.currency, locationsForCurrency])
  const company = scope === 'TREASURY' || value.source === 'COMPANY'

  return (
    <div className="commission-section" data-testid={testId}>
      <button type="button" className="btn-text commission-toggle" aria-expanded={value.open} onClick={() => set({ open: !value.open })}>
        {value.open ? '▾' : '◂'} عمولة (اختياري)
      </button>
      {value.open && (
        <div className="commission-body">
          <PillTabs
            label="اتجاه العمولة" value={value.direction} onChange={(v) => set({ direction: v })}
            options={[{ id: 'IN', label: 'نقبضها (إيراد)' }, { id: 'OUT', label: 'ندفعها (مصروف)' }]}
          />
          <div className="form-row">
            <div className="field">
              <label className="field-label">عملة العمولة</label>
              <SelectWrap>
                <select value={value.currency} onChange={(e) => set({ currency: e.target.value, account: '', location: '' })}>
                  <option value="" disabled>العملة</option>
                  {currencies.map((c) => <option key={c.code} value={c.code}>{c.name_ar}</option>)}
                </select>
              </SelectWrap>
            </div>
            <AmountStage
              id={`${idPrefix}-amount`} label={`مبلغ العمولة (${value.currency || '—'})`} value={value.amount}
              onChange={(v) => set({ amount: v })} currencyCode={value.currency || undefined}
            />
          </div>
          {scope === 'CLIENT' && (
            <PillTabs
              label="حساب العمولة" value={value.source} onChange={(v) => set({ source: v, account: '', location: '' })}
              options={[{ id: 'COMPANY', label: 'حساب شركة' }, { id: 'CLIENT', label: 'حساب العميل' }]}
            />
          )}
          {company ? (
            <AccountPicker
              value={value.account} onChange={(code) => set({ account: code })} spec={spec}
              label={value.direction === 'IN' ? 'الحساب الذي تُودَع فيه' : 'الحساب الذي تُخصم منه'}
              emptyMessage={!value.currency ? 'اختر عملة العمولة أولاً' : `لا حسابات شركة (صندوق أو بنك أو مراسل) بعملة ${value.currency}`}
            />
          ) : (
            <div className="field">
              <label className="field-label">موقع حساب العميل ({value.currency || '—'})</label>
              <SelectWrap>
                <select value={value.location} onChange={(e) => set({ location: e.target.value })} disabled={!value.currency}>
                  <option value="" disabled>الموقع</option>
                  {clientLocations.map((l) => <option key={l.code} value={l.code}>{l.name_ar}</option>)}
                </select>
              </SelectWrap>
            </div>
          )}
          <div className="rate-hint">زوج أسطر متوازن بعملة العمولة نفسها، منفصل عن فرق السعر في الأرباح.</div>
        </div>
      )}
    </div>
  )
}
