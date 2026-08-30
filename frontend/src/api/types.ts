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
  beneficiary_name_snapshot: string | null
  account_number_snapshot: string | null
  bank_name_snapshot: string | null
}

export interface ExchangeChainResponse {
  chain_ref: string
  step1: EntryResponse
  step2: EntryResponse
}

export interface CreditLimitOut {
  currency_code: string
  limit_amount: string
}

export interface ClientListRow {
  id: number
  code: string
  name_ar: string
  phone: string | null
  credit_allowed: boolean
  is_active: boolean
  balances: ClientBalance[]
  credit_limits: CreditLimitOut[]
  last_activity: string | null
}

export interface ClientDetail {
  id: number
  code: string
  name_ar: string
  name_en: string | null
  phone: string | null
  id_number: string | null
  credit_allowed: boolean
  is_active: boolean
  created_at: string
  balances: ClientBalance[]
  credit_limits: CreditLimitOut[]
}

export interface StatementRow {
  entry_id: number
  entry_no: string
  entry_date: string
  operation_type: string
  description: string | null
  debit: string
  credit: string
  running_balance: string
}

export interface StatementResponse {
  account_code: string
  currency_code: string
  location_code: string
  opening_balance: string
  closing_balance: string
  rows: StatementRow[]
}

export interface BeneficiaryFull {
  id: number
  name: string
  account_number: string
  bank_name: string | null
  currency_code: string
  purpose: string | null
  notes: string | null
  is_active: boolean
}

export interface PendingSwiftMovement {
  id: number
  amount: string
  currency_code: string
  transfer_date: string
  external_ref: string | null
  partner_name_ar: string | null
  out_entry_no: string | null
  partner_account_code: string | null
}

export interface CurrencyAmount {
  currency_code: string
  amount: string
}

export interface DashboardKpis {
  funds: CurrencyAmount[]
  client_liabilities: CurrencyAmount[]
}

export interface ProfitBreakdown {
  transfer_fee: CurrencyAmount[]
  exchange_spread: CurrencyAmount[]
  net_by_currency: CurrencyAmount[]
}

export interface TopClientRow {
  client_id: number
  code: string
  name_ar: string
  operation_count: number
}

export interface AlertRow {
  severity: 'critical' | 'warning' | 'info'
  code: string
  message_ar: string
}

export interface DashboardSummary {
  kpis: DashboardKpis
  today_profit: ProfitBreakdown
  top_clients: TopClientRow[]
  recent_entries: JournalEntryOut[]
  alerts: AlertRow[]
}

export interface LiquidityRow {
  currency_code: string
  location_code: string
  location_name_ar: string
  assets: string
  liabilities: string
  net: string
}

export interface AccountBalanceRow {
  code: string
  name_ar: string
  currency_code: string
  balance: string
}

export interface CorrespondentGroup {
  partner_id: number | null
  partner_name_ar: string
  accounts: AccountBalanceRow[]
}

export interface CorrespondentsResponse {
  groups: CorrespondentGroup[]
  totals: CurrencyAmount[]
}

export interface BoxesResponse {
  accounts: AccountBalanceRow[]
  totals: CurrencyAmount[]
}

export interface BanksResponse {
  accounts: AccountBalanceRow[]
  totals: CurrencyAmount[]
}

export interface LotRow {
  id: number
  lot_no: string
  swift_external_ref: string | null
  partner_name_ar: string | null
  arrival_date: string
  original_qty: string
  cost_rate: string
  remaining_qty: string
  num_sales: number
  weighted_avg_sale_rate: string | null
  total_profit: string
  profit_currency: string | null
  status: string
}

export interface LotConsumptionRow {
  consumed_at: string
  client_name_ar: string | null
  qty: string
  client_rate: string
  cost_share: string
  profit: string
  profit_currency: string
}

export interface LotDetail {
  lot: LotRow
  consumptions: LotConsumptionRow[]
}
