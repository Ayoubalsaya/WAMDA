| المسار | المعالج | استدعاء الواجهة | محرك/خدمة | الجداول المكتوبة (حياً) | سطر تدقيق (حياً) |
|---|---|---|---|---|---|
| `POST /auth/backup-codes/regenerate` | `app/routers/auth.py:135` | SecurityTab.tsx:28 | audit.log_write، backup_codes.generate | user_backup_codes+10 | BACKUP_CODES_GENERATED/users#14022 |
| `POST /auth/change-password` | `app/routers/auth.py:174` | ChangePasswordScreen.tsx:31 | auth_service.change_password | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `POST /auth/login` | `app/routers/auth.py:69` | useAuth.ts:30 | auth_service.InvalidCredentialsError، auth_service.InvalidTwoFactorCodeError، auth_service.generate_totp_setup_challenge، auth_service.login_step1، auth_service.login_step2_backup، auth_service.login_step2_setup، auth_service.login_step2_verify | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `POST /auth/logout` | `app/routers/auth.py:161` | useAuth.ts:39 | sessions.get_valid_session، sessions.revoke_session | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `POST /auth/recover/complete` | `app/routers/auth.py:196` | LoginScreen.tsx:58 | auth_service.InvalidCredentialsError، auth_service.recover_reset_password | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `POST /auth/recover/start` | `app/routers/auth.py:189` | LoginScreen.tsx:35 | auth_service.recover_get_security_question | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `POST /clients` | `app/routers/clients.py:143` | CreateClientModal.tsx:41 | audit.log_write | clients+1 | CLIENT_CREATED/clients#11596 |
| `PATCH /clients/{client_id}` | `app/routers/clients.py:171` | ClientDetailView.tsx:74 | — | — | **لا شيء** |
| `PUT /clients/{client_id}/credit-limits/{currency_code}` | `app/routers/clients.py:221` | ClientDetailView.tsx:280 | audit.log_write | — | CLIENT_CREDIT_LIMIT_SET/clients#11594 |
| `PUT /clients/{client_id}/credit-mode` | `app/routers/clients.py:195` | CreditControls.tsx:42 | audit.log_write | client_credit_limits+4 | CLIENT_CREDIT_MODE_CHANGED/clients#11594 |
| `POST /clients/{client_id}/portal/disable` | `app/routers/clients.py:423` | ClientPortalSection.tsx:72, ClientPortalSection.tsx:74 | client_portal_management.ClientNotFoundError، client_portal_management.disable | — | CLIENT_PORTAL_DISABLED/clients#11594 |
| `POST /clients/{client_id}/portal/enable` | `app/routers/clients.py:355` | ClientPortalSection.tsx:72, ClientPortalSection.tsx:74 | client_portal_invites.invite_url، client_portal_management.ClientNotFoundError، client_portal_management.enable | client_portal_invites+1 | CLIENT_PORTAL_ENABLED/clients#11594 |
| `POST /clients/{client_id}/portal/invite` | `app/routers/clients.py:376` | ClientPortalSection.tsx:72, ClientPortalSection.tsx:74 | client_portal_invites.invite_url، client_portal_management.ClientNotFoundError، client_portal_management.PortalNotEnabledError، client_portal_management.invite | client_portal_invites+1 | CLIENT_PORTAL_INVITED/clients#11594 |
| `POST /clients/{client_id}/portal/reset` | `app/routers/clients.py:399` | ClientPortalSection.tsx:72, ClientPortalSection.tsx:74 | client_portal_invites.invite_url، client_portal_management.ClientNotFoundError، client_portal_management.PortalNotEnabledError، client_portal_management.reset | client_portal_invites+1 | CLIENT_PORTAL_RESET/clients#11594 |
| `POST /clients/{client_id}/portal/unlock` | `app/routers/clients.py:440` | ClientPortalSection.tsx:72, ClientPortalSection.tsx:74 | client_portal_management.ClientNotFoundError، client_portal_management.unlock | — | CLIENT_PORTAL_UNLOCKED/clients#11594 |
| `POST /operations/adjustment` | `app/routers/operations.py:531` | OperationForm.tsx:614 | — | idempotency_keys+1, journal_entries+1, journal_lines+2 | **لا شيء** |
| `POST /operations/cash-transfer` | `app/routers/operations.py:346` | OperationForm.tsx:563 | — | account_balances+2, accounts+1, idempotency_keys+1, journal_entries+1, journal_lines+8 | **لا شيء** |
| `POST /operations/exchange` | `app/routers/operations.py:195` | OperationForm.tsx:545 | — | idempotency_keys+1, journal_entries+1, journal_lines+4 | **لا شيء** |
| `POST /operations/exchange-chain` | `app/routers/operations.py:239` | ExchangeWizard.tsx:157 | chain.execute_two_step_chain، exchange.execute_via_rates | account_balances+1, accounts+1, idempotency_keys+2, journal_entries+2, journal_lines+10 | **لا شيء** |
| `POST /operations/exchange/from-lot` | `app/routers/operations.py:220` | — | — | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `POST /operations/expense` | `app/routers/operations.py:483` | OperationForm.tsx:581 | — | idempotency_keys+1, journal_entries+1, journal_lines+2 | **لا شيء** |
| `POST /operations/local-move` | `app/routers/operations.py:375` | OperationForm.tsx:557 | — | idempotency_keys+1, journal_entries+1, journal_lines+4 | **لا شيء** |
| `POST /operations/opening` | `app/routers/operations.py:505` | OperationForm.tsx:604, OpeningBalancesTab.tsx:85 | — | account_balances+1, accounts+1, idempotency_keys+1, journal_entries+1, journal_lines+2, opening_balances+1 | **لا شيء** |
| `POST /operations/payment` | `app/routers/operations.py:172` | OperationForm.tsx:540 | — | idempotency_keys+1, journal_entries+1, journal_lines+2 | **لا شيء** |
| `POST /operations/receipt` | `app/routers/operations.py:152` | OperationForm.tsx:535 | — | account_balances+1, accounts+1, idempotency_keys+1, journal_entries+1, journal_lines+2 | **لا شيء** |
| `POST /operations/remit-out` | `app/routers/operations.py:399` | OperationForm.tsx:575 | — | idempotency_keys+1, journal_entries+1, journal_lines+2 | **لا شيء** |
| `POST /operations/swift-in` | `app/routers/operations.py:443` | OperationForm.tsx:591 | — | idempotency_keys+1, journal_entries+1, journal_lines+3 | **لا شيء** |
| `POST /operations/swift-out` | `app/routers/operations.py:422` | OperationForm.tsx:586 | — | idempotency_keys+1, journal_entries+1, journal_lines+2, swift_movements+1 | NEGATIVE_BALANCE_OVERRIDE/accounts#15650 |
| `POST /operations/swift-return` | `app/routers/operations.py:463` | OperationForm.tsx:598 | — | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `POST /operations/{entry_id}/cancel` | `app/routers/entry_actions.py:354` | EntryActions.tsx:27 | audit.log_write، chain.reverse_chain | journal_entries+1, journal_lines+2 | ENTRY_CANCELLED/journal_entries#41096 |
| `POST /operations/{entry_id}/comments` | `app/routers/entry_actions.py:473` | EntryActions.tsx:196 | audit.log_write | entry_comments+1 | ENTRY_COMMENT_ADDED/entry_comments#60 |
| `POST /operations/{entry_id}/edit` | `app/routers/entry_actions.py:387` | — | audit.log_write، chain.py | idempotency_keys+1, journal_entries+2, journal_lines+4 | ENTRY_EDITED/journal_entries#41099 |
| `POST /partners` | `app/routers/partners.py:46` | SettingsScreen.tsx:171 | — | partners+1 | **لا شيء** |
| `POST /partners/{partner_id}/accounts` | `app/routers/partners.py:71` | SettingsScreen.tsx:213 | accounts_repo.AccountNotFoundError، accounts_repo.AccountNumberExhaustedError، accounts_repo.create_partner_account | account_number_counters+1, accounts+1 | **لا شيء** |
| `POST /periods/close` | `app/routers/periods.py:46` | PeriodsTab.tsx:23 | audit.log_write | periods+1 | PERIOD_CLOSED/periods#None |
| `POST /periods/founding/close` | `app/routers/periods.py:132` | PeriodsTab.tsx:104 | audit.log_write، opening.FoundingPeriodAlreadyClosedError، opening.SuspenseBalanceAcknowledgmentRequiredError، opening.close_founding_period، opening.total_suspense_balance | لم يُنفَّذ حياً | نعم (ثابت) |
| `POST /periods/reopen` | `app/routers/periods.py:63` | PeriodsTab.tsx:23 | audit.log_write | — | PERIOD_REOPENED/periods#None |
| `POST /portal/change-password` | `app/routers/portal.py:121` | — | portal_auth_service.change_password | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `POST /portal/invite/accept` | `app/routers/portal.py:176` | PortalAcceptInviteScreen.tsx:58 | client_portal_invites.InvalidInviteError، client_portal_invites.PortalDisabledError، client_portal_invites.accept_invite | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `POST /portal/invite/verify` | `app/routers/portal.py:164` | PortalAcceptInviteScreen.tsx:30 | client_portal_invites.verify_invite | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `POST /portal/login` | `app/routers/portal.py:84` | usePortalAuth.ts:28 | portal_auth_service.InvalidPortalCredentialsError، portal_auth_service.login | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `POST /portal/logout` | `app/routers/portal.py:108` | usePortalAuth.ts:36 | sessions.get_valid_session، sessions.revoke_session | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `POST /portal/recover/complete` | `app/routers/portal.py:145` | — | portal_auth_service.InvalidPortalCredentialsError، portal_auth_service.recover_reset_password | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `POST /portal/recover/start` | `app/routers/portal.py:138` | — | portal_auth_service.recover_get_security_question | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `POST /reconciliation/statements` | `app/routers/reconciliation.py:92` | ReconciliationScreen.tsx:49 | — | partner_statement_lines+2, partner_statements+1 | **لا شيء** |
| `POST /reconciliation/statements/{statement_id}/auto-match` | `app/routers/reconciliation.py:146` | ReconciliationScreen.tsx:248 | — | — | **لا شيء** |
| `POST /reconciliation/statements/{statement_id}/lines/{line_id}/adjust` | `app/routers/reconciliation.py:241` | ReconciliationScreen.tsx:136 | — | idempotency_keys+1, journal_entries+1, journal_lines+2 | **لا شيء** |
| `PATCH /reconciliation/statements/{statement_id}/lines/{line_id}/match` | `app/routers/reconciliation.py:200` | ReconciliationScreen.tsx:221 | — | لم يُنفَّذ حياً | لا يظهر (ثابت) |
| `PATCH /reconciliation/statements/{statement_id}/lines/{line_id}/resolve` | `app/routers/reconciliation.py:215` | ReconciliationScreen.tsx:226 | — | — | **لا شيء** |
| `POST /settings/bank-accounts` | `app/routers/settings.py:76` | SettingsScreen.tsx:334 | accounts_repo.AccountNotFoundError، accounts_repo.AccountNumberExhaustedError، accounts_repo.create_bank_account | account_number_counters+1, accounts+1 | **لا شيء** |
| `POST /settings/client-currency-locations` | `app/routers/settings.py:264` | LocationsTab.tsx:129 | — | client_currency_locations+1 | **لا شيء** |
| `PUT /settings/company` | `app/routers/settings.py:52` | SettingsScreen.tsx:52 | — | — | **لا شيء** |
| `POST /settings/currencies` | `app/routers/settings.py:128` | CurrenciesTab.tsx:20 | accounts_repo.AccountNotFoundError، accounts_repo.create_currency_chart_of_accounts | account_number_assignments+12, accounts+12, currencies+1 | **لا شيء** |
| `PATCH /settings/currencies/{code}` | `app/routers/settings.py:153` | CurrenciesTab.tsx:114, CurrenciesTab.tsx:70 | — | — | **لا شيء** |
| `POST /settings/locations` | `app/routers/settings.py:207` | LocationsTab.tsx:19 | — | locations+1 | **لا شيء** |
| `PATCH /settings/locations/{code}` | `app/routers/settings.py:225` | LocationsTab.tsx:54, LocationsTab.tsx:88 | — | — | **لا شيء** |
| `POST /users` | `app/routers/users.py:30` | SettingsScreen.tsx:96 | user_management.InvalidRoleError، user_management.UsernameTakenError، user_management.create_user | users+1 | USER_CREATED/users#14023 |
| `PATCH /users/{user_id}` | `app/routers/users.py:63` | — | user_management.InvalidRoleError، user_management.LastAdminError، user_management.SelfLockoutError، user_management.UserNotFoundError، user_management.update_user | — | USER_UPDATED/users#14023 |