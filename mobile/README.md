# FPL Copilot — mobile

iOS and Android app (Expo SDK 57, React Native, Expo Router). It talks only to
the FastAPI backend and Supabase Auth; it holds no backend credentials.

## What exists

- Sign in with Apple (iOS) and Google (iOS + Android) through Supabase Auth.
- Session stored AES-GCM encrypted; the key is in the iOS Keychain / Android
  Keystore. Nothing sensitive is written to plain storage.
- Onboarding: Team ID → prove ownership with a code in the FPL team name →
  30-day trial starts.
- Subscriptions through Apple In-App Purchase and Google Play Billing, via
  RevenueCat. Prices and the annual saving come from the store, localised.
  After a purchase or restore the app asks the server to confirm with
  RevenueCat; the app never decides access. Restore and Manage subscription
  are in Profile, Restore also on the paywall.
- Home: gameweek, recommended action, captain, warnings, alerts.
- My Team: starting XI on a pitch with START / BENCH / SELL per player,
  availability and captaincy; bench order; captain ranking in safe, balanced
  and differential modes.
- Transfers: best plan over 1, 3 or 5 gameweeks with gain, hit, budget
  impact, confidence and the reasons behind each move; alternatives; "I've
  made these transfers" to record moves FPL cannot show before the deadline.
- Players: search (accent-insensitive), filters, sorting, infinite scroll,
  compare two players; a player screen with fixtures, projections, recent
  matches, sourced news and a BUY / SELL / HOLD verdict from the optimiser.
- Planner (from Transfers): the best transfer path over 1, 3 or 5 gameweeks,
  step by step, with free transfers, hits, bank, points per gameweek, the
  runner-up choice at each decision, and a warning when a buy planned for a
  later gameweek is close to a price rise.
- News (from Home): your alerts (mark read), the availability feed by
  category with its source, and price watch.
- Push notifications (Expo push service → APNs/FCM): squad availability
  alerts, price alerts and a deadline reminder two hours out, each switchable
  in Profile → Notifications. Permission is asked from a button, never on
  launch. Tapping one opens the player, News or Transfers. Signing out removes
  this phone from the account.
- Account deletion (Profile → Delete account), as both stores require: warns
  that a store subscription must be cancelled separately, confirms, then the
  server deletes the sign-in identity and all personal data.
- Profile.

Every screen decision is navigation only. The backend enforces ownership and
premium access on every request.

## One-time setup

1. **Supabase** (Dashboard → Authentication → Providers)
   - Apple: enable, add the iOS bundle ID `com.fplcopilot.app` as a client ID.
   - Google: enable, enter the **web** OAuth client ID and secret. Also enable
     *Skip nonce check*: the native Google iOS SDK adds a nonce the app cannot
     read, and Supabase rejects the token without this (see Known limits).
   - Settings → JWT expiry: 900–3600 s. Shorter limits how long a signed-out
     token keeps working on the API.
2. **Google Cloud Console** → Credentials: create a Web, an iOS
   (`com.fplcopilot.app`) and an Android client (package `com.fplcopilot.app`
   plus the SHA-1 of your signing key).
3. **Apple Developer**: enable *Sign in with Apple* on the App ID.
4. **Backend**: set `SUPABASE_URL` (and `SUPABASE_JWT_SECRET` only for a
   legacy-secret project) — see `backend/.env.example`.
5. **Stores and RevenueCat** (billing)
   - App Store Connect: one subscription group with two auto-renewing
     products, e.g. `fplc_pro_monthly` (€3.99) and `fplc_pro_annual` (€29.99).
     Product IDs must contain `monthly` or `annual` — the server reads the plan
     from them. No introductory free trial: the 30-day trial is ours. Enrol in
     the App Store Small Business Program (15%).
   - Google Play Console: the same two subscriptions.
   - RevenueCat: add both apps; create entitlement `pro` attached to all four
     products; a default offering with `$rc_monthly` and `$rc_annual`
     packages. Project settings → Restore Behavior: *Transfer if there are no
     active subscriptions*, so one store account cannot move a live
     subscription between our users.
   - RevenueCat → Integrations → Webhooks: URL
     `https://<api>/api/v1/billing/revenuecat/webhook`, a long random
     Authorization header value, and enable signing. Put the header value,
     signing secret and the secret API key in the backend environment.
6. `cp .env.example .env` and fill it in (public RevenueCat SDK keys included).

## Run

Native sign-in modules are not in Expo Go, so use a development build:

```bash
npm install
npx expo run:android      # needs Android SDK + emulator or device
npx expo run:ios          # macOS only
# or build in the cloud:
npx eas-cli@latest build --profile development --platform all
```

## Checks

```bash
npm run lint
npm run typecheck
npm test
npx expo-doctor
```

## Known limits

- *Skip nonce check* for Google weakens replay protection for Google ID tokens
  (a stolen ID token is usable until it expires, ~1 hour). Apple sign-in keeps
  full nonce protection.
- News covers FPL's official player news only. Rotation risk, manager
  comments, training updates and line-ups need press or journalist sources,
  which are not connected.
- The planner holds prices fixed; it flags likely rises but does not model them.
- Screens are covered by render tests but have not been run on a device.
- Purchases have only been tested against mocks. A sandbox purchase on a
  real device (App Store sandbox / Play licence testers) is needed before
  release.
- Stripe for web subscriptions is not built.
- No push for "your recommended transfer changed" (needs the optimiser run
  for every user in the background) or "unexpectedly benched" (needs a
  line-ups source).
- Google Play also requires a web page where users can request deletion
  without the app; that page is not built.
- `npm audit` reports high-severity issues in Expo's build tooling (node-forge,
  braces) and one moderate in `decode-uri-component`, which ships via
  expo-router. None has an upstream fix compatible with SDK 57; re-check before
  release.
