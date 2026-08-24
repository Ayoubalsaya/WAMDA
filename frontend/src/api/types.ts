export interface CurrentUser {
  id: number
  username: string
  full_name: string
  role: 'ADMIN' | 'ACCOUNTANT'
  must_change_password: boolean
}

export interface LoginResponse {
  status: 'ok' | 'totp_required' | 'totp_setup_required'
  must_change_password?: boolean
  totp_secret?: string
  provisioning_uri?: string
}

export interface Currency {
  code: string
  name_ar: string
  symbol: string
  decimals: number
  is_pivot: boolean
}

export interface Location {
  code: string
  name_ar: string
  country: string
}

export interface ClientCurrencyLocationPair {
  currency_code: string
  location_code: string
}

export interface AccountRef {
  code: string
  name_ar: string
  type: string
  currency_code: string | null
  location_code: string | null
  form: string | null
}

export interface ClientSearchResult {
  id: number
  code: string
  name_ar: string
  phone: string | null
  credit_allowed: boolean
}

export interface ClientBalance {
  account_code: string
  currency_code: string
  location_code: string | null
  balance: string
}

export interface Beneficiary {
  id: number
  name: string
  account_number: string
  bank_name: string | null
  currency_code: string
}

export interface JournalLineOut {
  account_code: string
  account_name_ar: string
  currency_code: string
  debit: string
  credit: string
  memo: string | null
}

export interface JournalEntryOut {
  id: number
  entry_no: string
  entry_date: string
  operation_type: string
  status: string
  description: string | null
  client_name_ar: string | null
  profit_amount: string | null
  profit_currency: string | null
  chain_ref: string | null
  lines: JournalLineOut[]
}

export interface EntryResponse {
  id: number
  entry_no: string
  status: string
  profit_amount: string | null
  profit_currency: string | null
  chain_ref: string | null
  chain_seq: number | null
  chain_total: number | null
}

export interface ExchangeChainResponse {
  chain_ref: string
  step1: EntryResponse
  step2: EntryResponse
}
