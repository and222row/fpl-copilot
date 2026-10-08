# Authentication

Who a caller is, how that is proved, and how the API decides what they may
reach. Supabase Auth owns identities and tokens; the backend only verifies.

## Overview

```text
 App / web                Supabase Auth                 FastAPI
 ─────────                ─────────────                 ───────
 Apple / Google sheet
   └─ ID token ─────────► signInWithIdToken
                          (checks audience, nonce)
          ◄────────────── access token (JWT) + refresh token
 every API call ───────────────────────────────────────► verify JWT locally
   Authorization: Bearer <access token>                  (JWKS, iss, aud, exp)
                                                          └─ user id = sub
```

- **Providers:** Sign in with Apple (iOS) and Google (iOS and Android) in the
  app; both through Supabase's OAuth redirect (PKCE) on the web. Phone OTP is
  deferred because SMS costs money. Email/password exists only in staging, for
  the Maestro tests.
- **One account, one id.** The Supabase user id (`sub`) is the account
  everywhere: our `users` table, RevenueCat's app user id, push device
  ownership. Supabase links identities that share a verified email.
- **No personal data copied.** Email and phone live only in Supabase's
  `auth.users`. The backend reads them from the token for `GET /me` and stores
  neither.

## Signing in on the app

`mobile/src/lib/auth.tsx`:

- **Apple:** the app generates a random nonce, passes its SHA-256 to Apple,
  and sends the raw nonce with the identity token to
  `supabase.auth.signInWithIdToken`. Supabase checks they match, so a captured
  identity token cannot be replayed.
- **Google:** the native Google SDK returns an ID token whose audience is the
  **web** client ID; Supabase validates against that. On iOS, Supabase's
  *Skip nonce check* must be on because the Google SDK adds a nonce the app
  cannot read. This weakens replay protection for Google ID tokens (usable
  until they expire, about an hour); Apple keeps full protection. Recorded as
  L8 in [SECURITY.md](../SECURITY.md).
- **Session storage:** the Supabase session (access and refresh token) is
  sealed with AES-256-GCM and stored in SQLite; only the key is in the iOS
  Keychain / Android Keystore (`AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY`, so not
  in backups or device transfers). Nothing sensitive is in plain storage.
  Android backups are off (`allowBackup: false`).
- **Refresh:** supabase-js refreshes the access token while the app is in the
  foreground. Each request takes the token from `getSession()`, which
  refreshes an expired one first.
- **Sign-out:** unregisters this phone's push token (so the next person on the
  phone does not get this account's alerts), then `signOut({scope: 'global'})`,
  which revokes every refresh token for the user. All cached queries are
  cleared on any sign-in or sign-out.
- **A 401 from the API** with a token we believed valid signs the app out
  locally and returns it to the sign-in screen.

## Signing in on the web

`frontend/src/lib/supabase.ts` and `frontend/src/components/AccountGate.tsx`:

- `signInWithOAuth` with `flowType: 'pkce'`: the redirect back carries a
  one-time code, never tokens. Supabase only redirects to URLs on its
  allowlist (Authentication → URL Configuration).
- The session is in `localStorage`, as it must be without a server. The
  site's Content-Security-Policy limits scripts to the site and `connect-src`
  to the site, the API and Supabase, so even injected script cannot send a
  token elsewhere.
- A 401 from the API signs the browser out locally.

## Verifying tokens (backend)

`backend/app/auth.py`, `decode_token`:

1. The key is chosen by the token's algorithm family and nothing else:
   `ES256`/`RS256` → the project's JWKS (cached 10 minutes, refetched at most
   every 30 seconds, last good keys kept during a Supabase outage); `HS256` →
   `SUPABASE_JWT_SECRET`, only if set. A token cannot talk the API into
   verifying HS256 with a public key.
2. Signature, `exp`, `iat`, `sub`, `aud` (`authenticated`) and `iss`
   (`{SUPABASE_URL}/auth/v1`) are required, with 30 seconds of clock leeway.
   The audience check rejects the publishable and secret keys, which share the
   signing key but are not user tokens.
3. Anonymous Supabase sessions are refused.
4. `current_user` additionally refuses accounts in `deleted_users`, then
   creates the local `users` row on first sight.

Verification is stateless, so a signed-out user's access token keeps working
until it expires. Set the Supabase JWT expiry to 15 minutes to bound that
(M7 in SECURITY.md). Deleted accounts are blocked immediately by the tombstone.

## Authorisation

FastAPI dependencies, applied per route (the [API reference](API.md#routes)
lists which each route uses):

| Dependency | Rule |
|---|---|
| `current_user` | A valid token for a non-deleted account. |
| `ManagerAccess` | Any route with `{manager_id}`: that FPL team must be connected to the caller. 403 otherwise. |
| `Premium` | A live trial or subscription from the entitlement service (see [PAYMENTS.md](PAYMENTS.md)). 402 `PREMIUM_REQUIRED` otherwise. |
| `JobToken` | Operator endpoints: `X-Job-Token`, constant-time compared. Fails closed in production if unset. |

Structural tests walk every route and fail if a `{manager_id}` route lacks
ownership, an advice route lacks `Premium`, or a write route is unguarded.

The client never supplies a user id, team id it owns, role, price or
entitlement that the server trusts. The app's screen routing
(`mobile/src/lib/gate.ts`) is navigation only; every request is re-checked.

## Proving FPL team ownership

FPL has no OAuth, and team IDs are public, so connecting a team must prove
control of it (`backend/app/routers/me.py`):

1. `POST /me/fpl-accounts` checks the team exists and issues a 6-character
   code (no `0/O/1/I`), valid 30 minutes. Whether someone else has already
   connected the team is not revealed.
2. The user adds the code to their FPL team name.
3. `POST /me/fpl-accounts/{id}/verify` reads the team from FPL, past both our
   cache and FPL's CDN, and looks for the code. Ten attempts per code; each
   attempt is committed before the check so failures count.
4. On success the team is connected. If another account had it, proving
   control takes it over, and the team's private state (pending transfers,
   alert links) is dropped so the new owner inherits none.

One team per account. Disconnecting drops the same private state.

## Account deletion

`DELETE /me` (Profile → Delete account), as both stores require:

1. Local deletions are staged: devices, preferences, push history, team
   links, claims, subscription row, alerts, recommendation history.
2. The Supabase identity is deleted with the admin API
   (`SUPABASE_SERVICE_KEY`). If that fails, nothing local is committed and
   the user sees an error, so an account is never half-deleted.
3. The local changes commit and a `deleted_users` tombstone is written.
4. The RevenueCat customer is deleted, best effort.

Kept on purpose: the trial row with its user detached (so deleting and
re-registering cannot mint a second trial for the same team) and the billing
audit trail with payloads redacted (accounting). A store subscription is not
cancelled by deletion; the app says so before confirming.

Google Play also requires a web page where users can request deletion without
the app. That page is not built yet.

## Setup checklist

Supabase (Authentication):

- Providers → Apple: enable; add the iOS bundle ID `com.fplcopilot.app` as a
  client ID. For web sign-in, an Apple **Services ID** with Supabase's
  callback URL as its return URL.
- Providers → Google: enable with the **web** client ID and secret; enable
  *Skip nonce check* (see above).
- Providers → Email: **off** in production; on only in staging for e2e.
- URL Configuration: the web dashboard's URL as Site URL and in Redirect URLs,
  plus your local origin (e.g. `http://localhost:3000`) for development.
- JWT expiry: 900 seconds.

Google Cloud Console → Credentials: a Web client, an iOS client
(`com.fplcopilot.app`) and an Android client (`com.fplcopilot.app` plus the
SHA-1 of each signing key, including EAS's and Play App Signing's).

Apple Developer: enable *Sign in with Apple* on the App ID.

Backend: `SUPABASE_URL`, and `SUPABASE_JWT_SECRET` only on a legacy-secret
project. App: `EXPO_PUBLIC_SUPABASE_URL`, `EXPO_PUBLIC_SUPABASE_KEY`, the Google
client IDs. Web: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_KEY`. See
[ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md).
