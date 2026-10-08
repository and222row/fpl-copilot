# End-to-end tests (Maestro)

Flows run against an **`e2e` build** pointed at **staging**, after
`backend/scripts/e2e_seed.py` has reset the test personas. CI runs them on an
Android emulator via `.github/workflows/e2e.yml` (manual or on `v*` tags).

## Why an e2e build

Google and Apple sign-in open system sheets bound to real accounts, which no
E2E tool can drive reliably. The `e2e` EAS profile sets `EXPO_PUBLIC_E2E=true`,
which shows an email/password sign-in on the sign-in screen. Safeguards:

- Only the `e2e` profile sets it; CI fails if any other profile does, and
  production pins it to `false`.
- It signs in against the **staging** Supabase project, the only one with the
  email provider enabled. Keep email sign-in **off** in production.
- The test accounts and their password exist only in staging.

## Personas (seeded)

| Email | State | Used by |
|---|---|---|
| `e2e-new@fplcopilot.test` | signed up, no team | onboarding |
| `e2e-trial@fplcopilot.test` | team, trial 20 days left | auth, trial, features, account, network |
| `e2e-expired@fplcopilot.test` | team, trial ended yesterday | trial, subscription |
| `e2e-subscriber@fplcopilot.test` | team, annual subscription | subscription |
| `e2e-delete@fplcopilot.test` | team, trial | delete-account (destroys it) |

## Run locally

```bash
# 1. staging backend env with ENVIRONMENT=staging, then:
E2E_ALLOW_SEED=1 E2E_PASSWORD=... E2E_FPL_TEAM_IDS=a,b,c,d python backend/scripts/e2e_seed.py
# 2. an e2e build on a simulator/emulator
npx eas-cli@latest build --profile e2e --platform ios      # or android
# 3. the flows
maestro test -e E2E_PASSWORD=... -e NEW_TEAM_ID=... mobile/.maestro
```

`npm test` also checks every `id` and literal text in these flows against the
app source (`src/__tests__/maestro-flows.test.ts`), so a renamed `testID` or
reworded button fails in seconds rather than on a device.

## Coverage of the specified scenarios

Each required scenario is covered where it can be exercised honestly. Things a
UI test cannot set up deterministically on staging (an FPL outage, a store
payment failing) are tested where the logic lives.

| Scenario | Where | Notes |
|---|---|---|
| Phone registration, invalid / expired OTP, resend | — | Phone sign-in deferred (SMS cost decision) |
| Google login, Apple login | Manual, release checklist | System sheets; real accounts |
| Logout | `auth/sign-out` | Relaunch stays signed out |
| Session restoration | `auth/session-restore` | Encrypted session survives restart |
| Wrong credentials | `auth/wrong-password` | |
| Account linking | Supabase automatic linking; manual check | Same verified email links identities |
| Valid FPL Team ID | `onboarding/valid-team-id` + backend `test_onboarding` | Flow reaches the ownership code; verification needs a real team rename |
| Invalid FPL Team ID | `onboarding/invalid-team-id` | |
| FPL API unavailable | backend `test_onboarding` (502/503), mobile `api.test` | Cannot take FPL down from a test |
| Squad imported | `features/my-team` | Pitch renders the squad |
| New user receives trial | backend `test_verify_connects_and_starts_the_trial` | |
| Trial active before expiry | `trial/trial-user` | |
| Trial expires / loses premium | `trial/expired-user` + backend boundary and 402 tests | |
| Client clock cannot extend trial | backend `test_client_clock_cannot_extend_the_trial` | Access uses only the server clock |
| Monthly / annual purchase, success, failure, cancel, renewal | Manual store sandbox + backend `test_billing` mapping | Store sheets cannot be automated reliably |
| Restore purchases | `subscription/restore-without-purchase` + manual sandbox restore | Asserts restore without purchase stays locked |
| Subscriber has access | `subscription/subscriber` | |
| Webhook delay | backend `test_premium_route_opens_after_a_purchase_and_closes_at_expiry` | Sync grants access without the webhook |
| Duplicate webhook | backend `test_duplicate_delivery_is_processed_once` | |
| Subscription expires | backend `test_access_ends_at_expiry_even_if_the_expiry_webhook_never_came` | |
| Cannot fake premium locally | `trial/expired-user` (relaunch) + backend `test_client_cannot_claim_premium` | |
| Paywall disclosure | `subscription/paywall-disclosure` | |
| Recommendations, captain, bench | `features/my-team` | |
| Transfers, planner | `features/transfers-and-planner` | |
| Player search, compare | `features/players` | |
| News, alerts | `features/news` | |
| Notification preferences | `account/notification-settings` | |
| Account deletion | `account/delete-account` | Credentials stop working |
| No internet | `network/offline` (Android) | |
| Slow internet / timeout, server error, rate limit | mobile `api.test` (timeout, 5xx, 429) | Not reproducible on staging on demand |
| Partial external outage | backend `test_resilience`, `test_players` (FPL down) | |

## Prerequisites on staging

- A season in progress (picks exist only once a gameweek has started), with
  the refresh running so projections exist.
- `E2E_FPL_TEAM_IDS`: four real public FPL team ids; `E2E_NEW_TEAM_ID`: a
  fifth, not connected to anyone.
- RevenueCat staging/sandbox keys in the build; products available to the
  emulator's store account for price display (not required for the flows).
