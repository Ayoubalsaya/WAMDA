import { ArrowDownUp, Ban, CreditCard, HandCoins, Landmark, PlusCircle, Receipt, Repeat, Scale, Send, Wallet2 } from 'lucide-react'
import './NewOperationPanel.css'

export interface OperationTile {
  id: string
  label: string
  desc: string
  color: string
  Icon: typeof Receipt
}

const LEVEL1: OperationTile[] = [
  { id: 'RECEIPT', label: 'قبض', desc: 'استلام من عميل', color: 'var(--money-in-text)', Icon: HandCoins },
  { id: 'PAYMENT', label: 'صرف', desc: 'تسليم لعميل', color: 'var(--money-out-text)', Icon: Wallet2 },
  { id: 'EXCHANGE', label: 'صرافة', desc: 'تحويل بين عملتين', color: 'var(--exchange-text)', Icon: ArrowDownUp },
  { id: 'CASH_TRANSFER', label: 'تحويل بعمولة', desc: 'نفس العملة بين موقعين', color: 'var(--sky-500)', Icon: Repeat },
  { id: 'REMIT_OUT', label: 'إرسال خارجي', desc: 'من رصيد العميل لتاجر خارجي بالعملة نفسها', color: 'var(--commission-text)', Icon: Send },
  { id: 'EXPENSE', label: 'مصروف', desc: 'بند تشغيلي', color: 'var(--text-secondary)', Icon: Receipt },
]

const LEVEL2: OperationTile[] = [
  { id: 'SWIFT_OUT', label: 'سويفت خروج', desc: 'من تركيا إلى الصين', color: 'var(--sky-500)', Icon: Send },
  { id: 'SWIFT_IN', label: 'سويفت وصول', desc: 'وصول لبنك الصين', color: 'var(--sky-500)', Icon: Landmark },
  { id: 'SWIFT_RETURN', label: 'سويفت مرتجع', desc: 'إلغاء تحويل صادر', color: 'var(--money-out-text)', Icon: Ban },
  { id: 'LOCAL_MOVE', label: 'نقل داخلي', desc: 'بين حسابات الشركة', color: 'var(--text-muted)', Icon: CreditCard },
  { id: 'OPENING', label: 'رصيد افتتاحي', desc: 'الفترة التأسيسية', color: 'var(--text-muted)', Icon: PlusCircle },
  { id: 'ADJUSTMENT', label: 'تسوية', desc: 'مدير فقط — سبب إلزامي', color: 'var(--exchange-text)', Icon: Scale },
]

interface NewOperationPanelProps {
  onSelect: (opType: string) => void
  onClose: () => void
}

export function NewOperationPanel({ onSelect, onClose }: NewOperationPanelProps) {
  return (
    <div className="modal-veil" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="new-op-panel card" onClick={(e) => e.stopPropagation()}>
        <h3 className="screen-title" style={{ fontSize: 'var(--fs-xl)' }}>عملية جديدة</h3>
        <p className="text-muted" style={{ fontSize: 'var(--fs-sm)', marginTop: 4 }}>اختر نوع العملية</p>
        <div className="new-op-grid">
          {LEVEL1.map((t) => <OpTile key={t.id} tile={t} onSelect={onSelect} />)}
        </div>
        <details className="new-op-more">
          <summary>المزيد</summary>
          <div className="new-op-grid" style={{ marginTop: 12 }}>
            {LEVEL2.map((t) => <OpTile key={t.id} tile={t} onSelect={onSelect} />)}
          </div>
        </details>
      </div>
    </div>
  )
}

function OpTile({ tile, onSelect }: { tile: OperationTile; onSelect: (id: string) => void }) {
  const { Icon } = tile
  return (
    <button type="button" className="new-op-tile" onClick={() => onSelect(tile.id)}>
      <span className="new-op-tile-icon" style={{ background: tile.color }}>
        <Icon size={20} strokeWidth={1.9} color="#fff" />
      </span>
      <span className="new-op-tile-label">{tile.label}</span>
      <span className="new-op-tile-desc">{tile.desc}</span>
    </button>
  )
}
