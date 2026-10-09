# Mobile app

The iOS and Android app in `mobile/`: Expo SDK 57, React Native 0.86, Expo
Router, TanStack Query, TypeScript. It talks only to the FastAPI backend,
Supabase Auth, RevenueCat and the stores; it holds no backend credential.

> Expo changes every SDK. Before touching an Expo or React Native API, read
> `mobile/AGENTS.md` and the versioned docs at
> `https://docs.expo.dev/versions/v57.0.0/`. Add packages with
> `npx expo install`, never plain `npm install <pkg>`, so versions match the SDK.

## Features

- **Sign in** with Apple (iOS) and Google (iOS and Android) through Supabase.
- **Onboarding:** enter an FPL Team ID → add a code to the FPL team name →
  verified, and the 30-day trial starts.
- **Paywall:** monthly and annual subscriptions through Apple IAP and Google
  Play Billing via RevenueCat, prices and the annual saving from the store,
  Restore purchases, renewal disclosure, terms and privacy links.
- **Home:** gameweek and deadline, the recommended action, captain, warnings,
  latest alerts.
- **My Team:** starting XI on a pitch with START / BENCH / SELL per player,
  availability and captaincy, bench order, captain ranking in safe / balanced
  / differential modes.
- **Transfers:** best plan over 1, 3 or 5 gameweeks with gain, hit, budget
  impact, confidence and reasons; alternatives; "I've made these transfers"
  to record moves FPL cannot show before the deadline.
- **Record transfers** (from Transfers and the squad banner): record any
  transfers already made in FPL, not just the recommended ones. Only legal,
  affordable replacements are offered (same position, at most 3 per club,
  within the bank), and the server checks the same rules.
- **Mini-leagues** (Home → Tools): your leagues with rank and movement; a
  league's table, the gap to the leader and the next place, the players most
  of the top ten own that you don't, and your differentials; head to head
  with any rival, with who your differences favour next gameweek.
- **Chip advisor** (Home → Tools): each chip's value now and at its best
  within the horizon, weeks left in its window, a plain verdict, and the
  doubles and blanks ahead.
- **Dream team** (Home → Tools): the best 15 for your own squad value plus
  bank, as a wildcard draft, marking the players you already own.
- **Track record** (Home → Tools): how the captain, lineup and transfer
  advice actually performed, graded automatically after each gameweek.
- **Planner** (from Transfers): the best transfer path step by step, with
  free transfers, hits, bank, points per gameweek, the runner-up at each
  decision, and a warning when a planned buy is close to a price rise.
- **Players:** accent-insensitive search, filters, sorting, infinite scroll,
  compare two players; a player screen with fixtures, projections, recent
  matches, sourced news and a BUY / SELL / HOLD verdict.
- **News** (from Home): your alerts (mark read), the availability feed by
  category with its source, price watch.
- **Push notifications:** availability alerts for your squad, price alerts,
  and a deadline reminder two hours out carrying your recommended transfers
  and captain, each switchable in Profile →
  Notifications. Permission is asked from a button, never at launch. Tapping
  one opens the player, News or Transfers.
- **Profile:** account and connected team, subscription status, Manage
  subscription, Restore purchases, notification settings, sign out,
  Disconnect team, **Delete account** (warns that a store subscription must be
  cancelled separately).
- **Crash reporting** through Sentry in release builds, with a retry screen
  instead of a blank app after a render crash.

## Layout

```text
mobile/
├── app.config.ts          app name, bundle id, plugins, EAS project id
├── eas.json               build profiles: development, e2e, preview, production
├── metro.config.js        Expo's Metro config plus Sentry debug ids
├── .maestro/              end-to-end flows (see TESTING.md)
└── src/
    ├── app/               routes (Expo Router: every file is a screen)
    │   ├── _layout.tsx    providers, the access gate, push handling, error screen
    │   ├── (tabs)/        Home, My Team, Transfers, Players, Profile (native tabs)
    │   ├── onboarding/    team id → verify
    │   ├── sign-in.tsx, paywall.tsx
    │   └── player/[id].tsx, compare.tsx, planner.tsx, news.tsx,
    │       notifications.tsx, delete-account.tsx
    ├── components/        shared UI (pitch, player photo, buttons, error view...)
    ├── hooks/             theme, debounce
    └── lib/
        ├── api.ts         typed API client, errors, timeouts
        ├── query.ts       React Query client, keys and hooks
        ├── gate.ts        which part of the app the user may see
        ├── auth.tsx       sign-in, sign-out, account deletion
        ├── supabase.ts, encrypted-storage.ts   session handling
        ├── billing.ts, subscription.ts         RevenueCat and plan wording
        ├── push.ts        registration, preferences, notification routing
        ├── monitoring.ts  Sentry setup and scrubbing
        ├── config.ts      the EXPO_PUBLIC_ values, validated
        └── squad.ts, planner.ts, format.ts     view logic, unit tested
```

## How it fits together

**The gate.** `src/app/_layout.tsx` reads the session, `GET /me` and
`GET /me/entitlements`, and `decideGate` picks one of: loading (splash stays
up), error (retry screen), signed-out, needs-team, needs-premium, ready. Each
maps to a `Stack.Protected` group, so a deep link cannot reach a screen the
user is not entitled to see. This is navigation only: every premium request
is re-checked by the server, and a 402 from any query refetches the
entitlement so the paywall appears.

**Data.** All server state goes through React Query (`src/lib/query.ts`):
results are fresh for 60 seconds, failures are retried twice except for
errors retrying cannot fix (400, 401, 402, 403, 404, 409, 422), and identical
requests are deduplicated. After the squad changes, everything derived from it
(recommendation, transfers, captain, alerts, planner) is invalidated together.
The cache is cleared on every sign-in and sign-out so one account's data never
shows to the next.

**API client** (`src/lib/api.ts`): adds the bearer token from
`supabase.auth.getSession()` (which refreshes it first if expired), times out
after 20 seconds (60–90 seconds for solver endpoints), and turns failures into
`ApiError` with a code: `NETWORK`, `TIMEOUT`, `UNAUTHORIZED`,
`PREMIUM_REQUIRED`, `RATE_LIMITED`, `SERVER`, or the server's own code. A 401
on a token we believed valid signs out locally.

**Sessions and sign-in:** see [AUTHENTICATION.md](AUTHENTICATION.md). In
short: the session is AES-GCM sealed with a Keychain/Keystore key, tokens
refresh only in the foreground, sign-out revokes all refresh tokens.

**Billing:** see [PAYMENTS.md](PAYMENTS.md). The RevenueCat customer id is the
Supabase user id; after any purchase or restore the app calls
`POST /billing/sync` and waits for the server's verdict.

**Push** (`src/lib/push.ts`): Expo push tokens, registered with
`PUT /me/devices` once the user is fully in, re-registered on each launch,
removed with `DELETE /me/devices/{token}` on sign-out. Android uses an
`alerts` channel. The server sends through the Expo push service, which
forwards to APNs and FCM; tokens Expo reports as unregistered are deleted.

**Images:** player photos use `expo-image` with memory and disk caching, and
fall back to a position badge for the roughly one player in eight FPL has no
photo for.

## Running it locally

Native modules (Google sign-in, Apple sign-in, RevenueCat, Sentry) are not in
Expo Go, so the app needs a **development build**.

1. Start the backend (see the [README](../README.md#quick-start)).
2. `cd mobile && npm install && cp .env.example .env`, then fill in `.env`:
   - `EXPO_PUBLIC_API_URL`: `http://<your computer's LAN IP>:8000` for a phone
     on the same Wi-Fi, `http://10.0.2.2:8000` for the Android emulator,
     `http://localhost:8000` for the iOS simulator. Plain http is allowed only
     in development builds.
   - The Supabase URL and publishable key, Google client IDs and RevenueCat
     public keys. See [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md#mobile-app-expo).
3. Build and run:

```bash
npx expo run:android
```

```bash
npx expo run:ios
```

   `run:android` needs the Android SDK and an emulator or device; `run:ios`
   needs macOS with Xcode. Without either, build a development client in the
   cloud and install it on your phone:

```bash
npx eas-cli@latest build --profile development --platform android
```

4. After the first build, `npx expo start` serves JavaScript changes to the
   installed development build with fast refresh. Rebuild only when native
   dependencies or `app.config.ts` change.

**On a real phone, from anywhere (Windows):** `npm run phone` starts a
Cloudflare quick tunnel to the dev server, prints the address, and runs the
dev server behind it. On the phone: FPL Copilot → Enter URL manually → that
address. Ctrl+C stops both. Point `EXPO_PUBLIC_API_URL` at the deployed API
(`https://fpl-copilot-api.onrender.com`) and nothing else needs to run on the
PC. The address changes on every run and stops working if the PC sleeps;
run it again and re-enter the new one. Needs `cloudflared`
(`winget install --id Cloudflare.cloudflared`).

Sign-in needs the Supabase providers configured (see
[AUTHENTICATION.md](AUTHENTICATION.md#setup-checklist)). Purchases need a
store build with sandbox testers; in a development build without RevenueCat
keys the paywall shows billing as unavailable.

## Checks

```bash
npm run lint
npm run typecheck
npm test
npx expo-doctor
```

CI runs all four, an audit of production dependencies, and two release
guards: only the `e2e` profile may enable the test sign-in, and a normal
bundle must not contain it. See [TESTING.md](TESTING.md).

## Builds

| EAS profile | For | Notes |
|---|---|---|
| `development` | local work | Development client, internal distribution. |
| `e2e` | Maestro | `EXPO_PUBLIC_E2E=true` (email sign-in for test personas), Android APK, iOS simulator build, staging values. |
| `preview` | internal testers | Release build, internal distribution. |
| `production` | the stores | Auto-incremented build number, `EXPO_PUBLIC_E2E` pinned `false`. |

Values come from EAS environments (`development`, `preview`, `production`);
set secrets such as `SENTRY_AUTH_TOKEN` there as sensitive variables. Release
steps are in [DEPLOYMENT.md](DEPLOYMENT.md#mobile-app).

## Known limits

- Screens are covered by render tests but have not yet been run end to end on
  a physical device.
- Purchases have only been tested against mocks; a sandbox purchase on real
  devices is required before release.
- Google sign-in on iOS needs Supabase's *Skip nonce check* (L8 in
  [SECURITY.md](../SECURITY.md)).
- News covers FPL's official player news only. Press conferences, line-ups
  and journalist sources are not connected.
- The planner holds prices fixed; it flags likely rises but does not model
  them.
- No push for "your recommended transfer changed" (needs the optimiser run for
  every user in the background) or "unexpectedly benched" (needs a line-ups
  source).
- Google Play requires a web page for requesting account deletion without the
  app; not built yet.
- `npm audit` reports high-severity issues in Expo's build tooling (H5) and a
  moderate one in `decode-uri-component` via expo-router (M5), neither in the
  shipped bundle and neither fixable within SDK 57.
