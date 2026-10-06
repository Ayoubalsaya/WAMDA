import { useCallback, useEffect, useState } from 'react'
import { api, ApiError, SESSION_EXPIRED_EVENT } from '../api/client'
import type { PortalLoginResponse, PortalMeResponse } from '../api/types'

// مطابق لـuseAuth.ts لكن على /portal/* بجلسة كوكي منفصلة (wamda_portal_session)
// — لا TOTP إطلاقاً (غير مذكور في §٧-٦ خلافاً لدخول الموظف).
export function usePortalAuth() {
  const [me, setMe] = useState<PortalMeResponse | null>(null)
  const [checking, setChecking] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const result = await api.get<PortalMeResponse>('/portal/me')
      setMe(result)
    } catch {
      setMe(null)
    } finally {
      setChecking(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // انتهاء الجلسة (خمول/سقف) أثناء الاستخدام ← شاشة الدخول
  useEffect(() => {
    const onExpired = () => setMe(null)
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired)
  }, [])

  const login = useCallback(
    async (code: string, password: string) => {
      const res = await api.post<PortalLoginResponse>('/portal/login', { code, password })
      if (res.status === 'ok') await refresh()
      return res
    },
    [refresh],
  )

  const logout = useCallback(async () => {
    await api.post('/portal/logout')
    setMe(null)
  }, [])

  return { me, checking, login, logout, refresh }
}

export { ApiError }
