import { Fragment, useState } from 'react'
import { api } from '../../api/client'
import type { AuditLogRow } from '../../api/types'
import { useReferenceData } from '../../hooks/useReferenceData'
import { displayAudit } from '../../lib/auditDisplay'

export function AuditLogTab() {
  const { currencies } = useReferenceData()
  const [rows, setRows] = useState<AuditLogRow[] | null>(null)
  const [entity, setEntity] = useState('')
  const [action, setAction] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [expandedId, setExpandedId] = useState<number | null>(null)

  async function load() {
    const params = new URLSearchParams()
    if (entity) params.set('entity', entity)
    if (action) params.set('action', action)
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    const data = await api.get<AuditLogRow[]>(`/audit-log?${params.toString()}`)
    setRows(data)
  }

  return (
    <div className="card">
      <div className="card-title" style={{ marginBottom: 12 }}>سجل التدقيق</div>
      <div className="op-row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 16, alignItems: 'flex-end' }}>
        <div className="field"><label className="field-label" htmlFor="al-entity">الكيان</label><input id="al-entity" value={entity} onChange={(e) => setEntity(e.target.value)} placeholder="مثال: periods" /></div>
        <div className="field"><label className="field-label" htmlFor="al-action">الإجراء</label><input id="al-action" value={action} onChange={(e) => setAction(e.target.value)} placeholder="مثال: PERIOD_CLOSED" /></div>
        <div className="field"><label className="field-label" htmlFor="al-from">من تاريخ</label><input id="al-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /></div>
        <div className="field"><label className="field-label" htmlFor="al-to">إلى تاريخ</label><input id="al-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} /></div>
        <button type="button" className="btn btn-primary" onClick={() => void load()}>بحث</button>
      </div>
      {rows === null ? (
        <p className="text-muted" style={{ fontSize: 'var(--fs-sm)' }}>اضغط "بحث" لعرض السجل (قد يكون طويلاً — يبدأ فارغاً عمداً)</p>
      ) : (
        <table className="data-table">
          <thead><tr><th>الوقت</th><th>الفاعل</th><th>الإجراء</th><th>الكيان</th><th></th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <Fragment key={r.id}>
                <tr
                  className="acc-lot-row"
                  onClick={() => setExpandedId(expandedId === r.id ? null : r.id)}
                >
                  <td className="num">{new Date(r.at).toLocaleString('ar-LY')}</td>
                  <td>{r.actor_label} <span className="text-muted" style={{ fontSize: 'var(--fs-2xs)' }}>({r.actor_type === 'USER' ? 'موظف' : 'عميل'})</span></td>
                  <td><span className="badge badge-chain">{r.action}</span></td>
                  <td className="text-muted">{r.entity}{r.entity_id ? ` #${r.entity_id}` : ''}</td>
                  <td className="text-muted">{expandedId === r.id ? '▲' : '▼'}</td>
                </tr>
                {expandedId === r.id && (r.before_json || r.after_json) && (
                  <tr>
                    <td colSpan={5} style={{ background: 'var(--sky-50)', padding: 'var(--space-3)' }}>
                      {r.before_json && (
                        <div style={{ marginBottom: 6 }}>
                          <div className="text-muted" style={{ fontSize: 'var(--fs-2xs)' }}>قبل</div>
                          <pre className="num" style={{ fontSize: 'var(--fs-2xs)', whiteSpace: 'pre-wrap' }}>{JSON.stringify(displayAudit(r.before_json, currencies), null, 2)}</pre>
                        </div>
                      )}
                      {r.after_json && (
                        <div>
                          <div className="text-muted" style={{ fontSize: 'var(--fs-2xs)' }}>بعد</div>
                          <pre className="num" style={{ fontSize: 'var(--fs-2xs)', whiteSpace: 'pre-wrap' }}>{JSON.stringify(displayAudit(r.after_json, currencies), null, 2)}</pre>
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="text-muted">لا سجلات مطابقة</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  )
}
