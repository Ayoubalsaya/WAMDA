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

export interface PortalLoginResponse {
  status: string
  must_change_password?: boolean
}

export interface PortalMeResponse {
  code: string
  name_ar: string
  must_change_password: boolean
}

// §٧-١١ التقارير
export interface DebtsByCurrencyRow {
  currency_code: string
  total_owed: string
  client_count: number
}

export interface ProfitByPeriodRow {
  period_label: string
  transfer_fee: CurrencyAmount[]
  exchange_spread: CurrencyAmount[]
  net_by_currency: CurrencyAmount[]
}

export interface TrialBalanceRow {
  account_code: string
  account_name_ar: string
  account_type: string
  currency_code: string | null
  debit: string
  credit: string
}

export interface TrialBalanceResponse {
  rows: TrialBalanceRow[]
  total_debit_by_currency: CurrencyAmount[]
  total_credit_by_currency: CurrencyAmount[]
  balanced: boolean
}

export interface IncomeStatementLine {
  account_code: string
  account_name_ar: string
  currency_code: string
  amount: string
}

export interface IncomeStatementResponse {
  revenue: IncomeStatementLine[]
  expense: IncomeStatementLine[]
  net_by_currency: CurrencyAmount[]
}

export interface ClientProfitabilityRow {
  client_id: number
  client_code: string
  client_name_ar: string
  profit_by_currency: CurrencyAmount[]
  operation_count: number
}

export interface ActivityRow {
  key: string
  entry_count: number
}

export interface CorrespondentActivityRow {
  partner_id: number
  partner_name_ar: string
  entry_count: number
  total_debit_by_currency: CurrencyAmount[]
  total_credit_by_currency: CurrencyAmount[]
}

export interface SwiftHistoryRow {
  id: number
  status: string
  amount: string
  currency_code: string
  transfer_date: string
  received_date: string | null
  external_ref: string | null
  partner_name_ar: string | null
}

export interface LossMakingEntryRow {
  entry_id: number
  entry_no: string
  entry_date: string
  operation_type: string
  client_name_ar: string | null
  profit_amount: string
  profit_currency: string
}

export interface BalanceOverrideRow {
  id: number
  created_at: string
  action: string
  account_code: string | null
  entry_no: string | null
  reason: string | null
  actor_username: string | null
}

export interface EmergencyEntryRow {
  entry_id: number
  entry_no: string
  entry_date: string
  operation_type: string
  real_operation_time: string | null
  backdate_reason: string | null
}

export interface FoundingReconciliationResponse {
  suspense_balance_by_currency: CurrencyAmount[]
  opening_balances_total_by_currency: CurrencyAmount[]
  opening_balances_count: number
  open_reconciliation_items: number
}

// §٧-٩ المطابقة
export interface StatementLineOut {
  id: number
  value_date: string
  description: string | null
  amount: string
  status: 'OPEN' | 'RESOLVED'
  matched_entry_id: number | null
  matched_entry_no: string | null
}

export interface PartnerStatementSummary {
  id: number
  partner_id: number
  partner_name_ar: string
  period_from: string
  period_to: string
  imported_at: string
  total_lines: number
  open_lines: number
}

export interface PartnerStatementDetail {
  id: number
  partner_id: number
  partner_name_ar: string
  period_from: string
  period_to: string
  imported_at: string
  lines: StatementLineOut[]
}

export interface AutoMatchResponse {
  matched_count: number
  statement: PartnerStatementDetail
}

// §٧-١٤ الإعدادات
export interface CompanyProfile {
  name_ar: string
  logo_data_url: string | null
}

export interface UserListRow {
  id: number
  username: string
  full_name: string
  role: string
  is_active: boolean
  must_change_password: boolean
  last_login_at: string | null
}

export interface PartnerRow {
  id: number
  code: string
  name_ar: string
  name_en: string | null
  country: string
  contact_phone: string | null
  notes: string | null
  is_active: boolean
}

export interface AccountOut {
  id: number
  code: string
  name_ar: string
  currency_code: string | null
  location_code: string | null
  form: string | null
  partner_id: number | null
}

// §٩ المرحلة ١١ — إقفال الفترات
export interface PeriodRow {
  year: number
  month: number
  is_closed: boolean
  closed_by_username: string | null
  closed_at: string | null
}

export interface FoundingPeriodStatus {
  is_open: boolean
  closed_at: string | null
  closed_by_username: string | null
  suspense_balance_by_currency: Record<string, string>
}

// §٩ المرحلة ١١ — سجل التدقيق
export interface AuditLogRow {
  id: number
  at: string
  actor_type: 'USER' | 'CLIENT'
  actor_id: number
  actor_label: string
  action: string
  entity: string
  entity_id: number | null
  before_json: Record<string, unknown> | null
  after_json: Record<string, unknown> | null
}
