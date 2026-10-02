import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { CurrentUser, LoginResponse } from '../api/types'

export function useAuth() {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [checking, setChecking] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const me = await api.get<CurrentUser>('/auth/me')
      setUser(me)
    } catch {
      setUser(null)
    } finally {
      setChecking(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const login = useCallback(
    async (username: string, password: string, totpCode?: string, totpSecretSetup?: string, backupCode?: string) => {
      const body: Record<string, string> = { username, password }
      if (totpCode) body.totp_code = totpCode
      if (totpSecretSetup) body.totp_secret_setup = totpSecretSetup
      if (backupCode) body.backup_code = backupCode
      const res = await api.post<LoginResponse>('/auth/login', body)
      // الرموز الاحتياطية تُعرض إلزامياً قبل دخول التطبيق: الجلسة قائمة لكن `user` لا يُحمَّل حتى يُقِرّ المستخدم (LoginScreen ← refresh)
      if (res.status === 'ok' && !res.backup_codes) await refresh()
      return res
    },
    [refresh],
  )

  const logout = useCallback(async () => {
    await api.post('/auth/logout')
    setUser(null)
  }, [])

  return { user, checking, login, logout, refresh }
}

export { ApiError }
