import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AccountRef, ClientCurrencyLocationPair, Currency, Location } from '../api/types'

export function useReferenceData() {
  const [currencies, setCurrencies] = useState<Currency[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [pairs, setPairs] = useState<ClientCurrencyLocationPair[]>([])
  const [accounts, setAccounts] = useState<AccountRef[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      const [c, l, p, a] = await Promise.all([
        api.get<Currency[]>('/reference/currencies'),
        api.get<Location[]>('/reference/locations'),
        api.get<ClientCurrencyLocationPair[]>('/reference/client-currency-locations'),
        api.get<AccountRef[]>('/reference/accounts'),
      ])
      if (cancelled) return
      setCurrencies(c)
      setLocations(l)
      setPairs(p)
      setAccounts(a)
      setLoading(false)
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  function locationsForCurrency(currencyCode: string): Location[] {
    const allowedCodes = new Set(pairs.filter((p) => p.currency_code === currencyCode).map((p) => p.location_code))
    return locations.filter((l) => allowedCodes.has(l.code))
  }

  return { currencies, locations, pairs, accounts, loading, locationsForCurrency }
}
