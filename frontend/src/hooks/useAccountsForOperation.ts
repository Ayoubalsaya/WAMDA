import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AccountRef } from '../api/types'

export interface AccountFieldSpec {
  operationType: string
  field: string
  currencyCode: string
  locationCode?: string
}

interface State {
  accounts: AccountRef[]
  loading: boolean
}

// حسابات مُصفّاة بحسب (نوع العملية × دور الحقل × العملة × الموقع) عبر
// GET /reference/accounts/for-operation — spec=null يعني "هذا الحقل غير
// نشط الآن" (تبويب آخر مفعَّل)، فلا يُطلَق أي جلب.
export function useAccountsForOperation(spec: AccountFieldSpec | null): State {
  const [state, setState] = useState<State>({ accounts: [], loading: false })

  useEffect(() => {
    if (!spec || !spec.currencyCode) {
      setState({ accounts: [], loading: false })
      return
    }
    let cancelled = false
    setState((s) => ({ ...s, loading: true }))
    const params = new URLSearchParams({
      operation_type: spec.operationType, field: spec.field, currency_code: spec.currencyCode,
    })
    if (spec.locationCode) params.set('location_code', spec.locationCode)
    void api
      .get<AccountRef[]>(`/reference/accounts/for-operation?${params}`)
      .then((rows) => { if (!cancelled) setState({ accounts: rows, loading: false }) })
      .catch(() => { if (!cancelled) setState({ accounts: [], loading: false }) })
    return () => { cancelled = true }
  }, [spec?.operationType, spec?.field, spec?.currencyCode, spec?.locationCode])

  return state
}
