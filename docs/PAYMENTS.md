# Payments

How FPL Copilot charges, how access is decided, and why it is built this way.

## The offer

- **Free trial:** 30 days, starting when the user first proves an FPL team.
  One per account and one per FPL team, ever.
- **FPL Copilot Pro:** monthly or annual auto-renewing subscription. The spec
  sets €4/month and €30/year; the stores only allow fixed price points, so the
  products are priced at the nearest ones (for example €3.99 and €29.99). The
  app shows whatever price and currency the store returns, never a hardcoded
  one.

## Architecture

```text
 App ──purchase──► App Store / Google Play ──receipt──► RevenueCat
  │                                                       │  validates
  │                                              webhook  │
  │                                                       ▼
  └──POST /billing/sync──► FastAPI ──GET /v1/subscribers/{user id}──► RevenueCat
                              │
                              ▼
                     subscriptions table ──► entitlement service ──► 402 or access
```

- **Apple In-App Purchase on iOS, Google Play Billing on Android, through
  RevenueCat.** RevenueCat validates receipts, tracks renewals, refunds and
  billing retries for both stores, and has a free tier. The app uses its SDK
  (`react-native-purchases`); the backend uses its REST API.
- **The server decides access, from RevenueCat, never from the client.** The
  app's purchase result, a webhook body, a client clock or a client-sent
  product or price are never trusted. Both the webhook and the app's sync are
  only cues for the server to re-read the customer from RevenueCat with the
  secret key.
- **Stripe** is for web subscriptions later and is not built. The web
  dashboard sells nothing today.

## Store rules this relies on

Digital subscriptions used inside an iOS or Android app have to be sold
through the store's own billing (App Store Review Guidelines 3.1.1 and 3.1.2;
Google Play's Payments policy). Regional exceptions exist (for example
alternative billing or external purchase links in some markets), but each has
its own entitlement, fee and disclosure rules, and they change often. This
build uses store billing everywhere, which is compliant in every market.
**Re-read the current guidelines before each release** if you change any of
this, particularly before adding web purchases or links to them.

Consequences in the code:

- The app never links to or mentions a cheaper way to pay elsewhere.
- The web dashboard tells users without access to subscribe in the app; it has
  no purchase flow and no payment link.
- Store fees: enrol in the App Store Small Business Program (15%). Google
  Play's fee on subscriptions is 15%.
- Our 30-day trial is ours, not a store introductory offer. Configure **no**
  free trial on the store products, or users would get two.

## Entitlements

`backend/app/services/entitlements.py` is the only answer to "may this user
use premium features right now?". `GET /me/entitlements` returns it, and the
`Premium` dependency enforces it on every advice route.

```json
{"premium": true, "status": "TRIALING", "plan": null, "provider": "TRIAL",
 "trial_started_at": "...", "trial_ends_at": "...", "subscription_ends_at": null}
```

Rules, in order:

1. A stored subscription that is not `EXPIRED` and whose expiry (or grace
   period end) is in the future → premium, with its status (`ACTIVE`,
   `CANCELED` but paid up, `PAST_DUE` in a billing grace period). No expiry
   means a lifetime grant.
2. Otherwise a trial that has not ended → premium, `TRIALING`.
3. Otherwise `EXPIRED` if there ever was a subscription or trial.
4. Otherwise `NONE` (signed up, no team proved yet).

Always the server's clock, evaluated at request time: access ends at the
stored expiry even if the store's expiry webhook never arrives, and changing
the phone's clock does nothing.

There is no `entitlements` table: entitlement is computed from `trials` and
`subscriptions` on every request, so it cannot drift from them.

## The trial

Started inside `POST /me/fpl-accounts/{id}/verify` by
`start_trial_if_eligible`, only if neither this user nor this team has ever
had one. The `trials` row is keyed by team and survives account deletion with
its user detached, so deleting the account and signing up again with the same
team gets no second trial.

## Purchase flow (app)

`mobile/src/lib/billing.ts`, `mobile/src/app/paywall.tsx`:

1. On sign-in the app calls `Purchases.logIn(<Supabase user id>)`, so the
   RevenueCat customer **is** the account. Sign-out logs out of RevenueCat.
2. The paywall loads the current offering (`$rc_monthly`, `$rc_annual`) and
   shows the store's localised prices and the annual saving.
3. `purchasePackage` → the store sheet → on success `POST /billing/sync`. The
   server re-reads RevenueCat and returns the new entitlement; the app
   refetches and the gate opens. The app never unlocks itself.
4. Cancelled purchases do nothing. Pending ones (Ask to Buy, slow payment
   methods) say so; the webhook grants access when the store completes them.

**Restore purchases** is on the paywall and in Profile: `restorePurchases`,
then the same sync. RevenueCat's Restore Behavior must be *Transfer if there
are no active subscriptions*, so one store account cannot move a live
subscription between two of our users.

**Manage subscription** in Profile opens the store's own management screen.

**Paywall disclosure** (both stores require it): price and period per plan
from the store, auto-renewal unless cancelled at least 24 hours before the
period ends, where to manage or cancel, Restore purchases, and links to the
terms and privacy policy.

## The webhook

`POST /api/v1/billing/revenuecat/webhook` (`backend/app/routers/billing.py`):

1. **Authenticated:** the `Authorization` header must equal
   `REVENUECAT_WEBHOOK_AUTH` (constant-time compare), and with
   `REVENUECAT_WEBHOOK_SIGNING_SECRET` set (required in production) the
   `X-RevenueCat-Webhook-Signature` HMAC must verify and be under five minutes
   old, so a captured delivery cannot be replayed. Bodies over 64 KB are
   refused.
2. **Idempotent:** each event id is stored in `billing_events`. A processed
   event is answered `duplicate`; concurrent deliveries of one event are
   resolved by the unique index.
3. **Re-read, not trusted:** for every one of our users the event touches
   (`app_user_id`, aliases, or both sides of a `TRANSFER`), the server calls
   `GET /v1/subscribers/{id}` and stores what RevenueCat says. Anonymous
   RevenueCat ids are ignored.
4. **Retries:** if RevenueCat cannot be reached the event keeps its error and
   the webhook answers 502, so RevenueCat retries. An event still failing an
   hour after it arrived is logged as an error (Sentry), and shows in
   `GET /health/ops`.

`POST /billing/sync` takes no body, reads only the caller's own customer, and
is rate-limited. It exists so access does not wait for the webhook.

## What is stored

`subscriptions` (one row per user): provider (`APPLE`, `GOOGLE`, `STRIPE`,
`PROMOTIONAL`), status, plan (`MONTHLY`/`ANNUAL`, read from the product id,
which must contain `monthly` or `annual`), product id, expiry, grace expiry,
`is_sandbox`, the store's management URL, last sync time.

`billing_events`: every delivery, as the audit trail. On account deletion the
user id and payload are redacted and the row is kept for accounting.

## Edge cases

| Case | Behaviour |
|---|---|
| Webhook late or lost | `/billing/sync` grants access right after purchase; expiry is enforced from the stored date regardless. |
| Expiry webhook never arrives | Access ends at the stored expiry anyway. |
| Billing problem | Store grace period: `PAST_DUE`, still premium until the grace end. |
| User cancels | `CANCELED`, premium until the paid period ends. |
| Refund | RevenueCat removes the entitlement; the next webhook re-read records `EXPIRED`. |
| Same store account, two of our users | Restore Behavior blocks moving an active subscription; a `TRANSFER` event re-reads both users. |
| Account deleted with an active subscription | Not cancelled (only the user can, in the store); the app warns first. RevenueCat customer deleted best effort. |
| Sandbox purchase | Grants access (App Review buys with sandbox accounts against production builds). Recorded as `is_sandbox`; check before widening TestFlight. |

## Setup checklist

- **App Store Connect:** one subscription group with two auto-renewing
  products, e.g. `fplc_pro_monthly` and `fplc_pro_annual`; no introductory
  offer; Small Business Program; paid apps agreement, tax and banking.
- **Google Play Console:** the same two subscriptions (base plans), no free
  trial offer; payments profile.
- **RevenueCat:** both apps; entitlement `pro` attached to all four products;
  a default offering with `$rc_monthly` and `$rc_annual`; Restore Behavior
  *Transfer if there are no active subscriptions*; webhook to
  `https://<api>/api/v1/billing/revenuecat/webhook` with a long random
  Authorization value and signing enabled.
- **Backend:** `REVENUECAT_SECRET_KEY`, `REVENUECAT_WEBHOOK_AUTH`,
  `REVENUECAT_WEBHOOK_SIGNING_SECRET`.
- **App:** `EXPO_PUBLIC_REVENUECAT_IOS_KEY`, `EXPO_PUBLIC_REVENUECAT_ANDROID_KEY`
  (public SDK keys only).

## Testing

- Backend `tests/test_billing.py`: subscriber parsing for every status,
  webhook authentication, signature and replay window, duplicates,
  transfers, RevenueCat outages, access opening after sync and closing at
  expiry without a webhook. `tests/test_onboarding.py`: trial eligibility,
  boundaries and the server clock.
- App: paywall render tests (`src/__tests__/paywall.test.tsx`) and
  `billing.test.ts` (purchasing as the signed-in user, offerings, store
  errors, the annual saving, subscription wording).
- **Not automatable:** real store sheets. Before release, buy, restore, cancel
  and let a renewal lapse with App Store sandbox and Play licence testers on
  real devices. Purchases have so far only been tested against mocks.
