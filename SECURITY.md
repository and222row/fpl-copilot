# Security

## Reporting a vulnerability

Email the maintainer rather than opening a public issue. Include steps to
reproduce. Do not test against production data you do not own.

## Pre-release security review — 2026-10-08

Scope: FastAPI backend, Expo mobile app, Next.js dashboard, CI, and the
Supabase / RevenueCat / Expo push integrations. Method: dependency audits
(`pip-audit`, `npm audit`), a full-history secret scan, code review against the
OWASP API Security Top 10 and OWASP MASVS, and a check of each finding by test
or by inspecting build output. Fixes are covered by tests; where a test was
added it was confirmed to fail without the fix.

### Findings

| ID | Severity | Finding | Status |
|---|---|---|---|
| C1 | Critical | Supabase serves every `public` table through its Data API to anyone holding the publishable key, which the mobile app ships. Alembic-created tables had row level security off, so that key alone could read or rewrite users, subscriptions, devices and squads. | **Fixed in code** — migration `e9a1c3d5f7b8` enables RLS on every public table and revokes the API roles' privileges, now and by default for new tables. Production startup logs an error for any public table without RLS. **Takes effect only once the migration runs.** |
| C2 | Critical | `AUTH_REQUIRED=false` in production: anonymous callers reach every team route and premium feature, bypassing ownership checks and the paywall. Kept because the web dashboard had no sign-in. | **Fixed** — the web dashboard signs in with Supabase (same accounts, team verification and access rules as the app; see below) and `render.yaml` sets `AUTH_REQUIRED=true`. Production startup still logs an error if it is ever off. |
| C3 | Critical | Next.js 16.3.2: remote code execution (image optimisation, `next/og`, Windows hosts), SSRF in image optimisation, cache poisoning; `sharp` and `source-map-js` advisories. | **Fixed** — Next.js 16.3.8, sharp 0.35.5, source-map-js 1.2.2. `npm audit`: 0. |
| H1 | High | Starlette 0.41.3 (via FastAPI 0.115.5): eight advisories, including denial of service. | **Fixed** — FastAPI 0.143.0 / Starlette 1.7.0. `pip-audit`: 0. The upgrade changed how FastAPI stores included routers, which silently emptied the structural security tests (ownership, premium, guarded writes) so they passed while checking nothing; they now walk routes through a helper cross-checked against the OpenAPI schema. |
| H2 | High | Operator endpoints (sync, rebuild, refresh) were open whenever `JOB_TOKEN` was unset. | **Fixed** — fail closed (503) in production. |
| H3 | High | The billing webhook accepted unsigned deliveries, which a captured request could replay. | **Fixed** — signing required in production (503 otherwise); signed deliveries older than 5 minutes are refused. |
| H4 | High | Rate limits for anonymous callers keyed on the socket peer, which behind Render's proxy is the proxy — one shared bucket for everyone. | **Fixed** — `TRUSTED_PROXY_HOPS=1` takes the entry Render appends to `X-Forwarded-For`, never the client-written leftmost one. **Verify on first deploy** that Render appends rather than replaces. |
| H5 | High | `npm audit` in the mobile app reports `node-forge` and `braces`. | **Accepted** — both are in Expo's CLI/Metro tooling, not the app bundle; no fix within SDK 57. CI fails on any critical; re-check each SDK upgrade. |
| M1 | Medium | Swagger UI, ReDoc and the OpenAPI schema were public in production, mapping every route including operator ones. | **Fixed** — disabled in production. |
| M2 | Medium | Some 404s echoed internal exception text to clients. | **Fixed** — generic messages; details go to the logs. |
| M3 | Medium | No request size limit. | **Fixed** — 1 MB, counting bytes actually received, so a chunked body with no length cannot stream unbounded. |
| M4 | Medium | The client's `X-Request-ID` was echoed into logs and response headers unchecked. | **Fixed** — only `[A-Za-z0-9._-]{1,64}` is reused. |
| M5 | Medium | `decode-uri-component` (via expo-router) can be made slow by a crafted deep link. | **Accepted** — no upstream fix in SDK 57; impact is limited to the user's own app session. |
| M6 | Medium | The backend connects as the Supabase `postgres` owner role. RLS does not apply to the owner, which the backend relies on, but a leaked `DATABASE_URL` is full database access. | **Open — operational.** Keep `DATABASE_URL` only in Render's environment; rotate it if exposed; restrict by IP once on a plan with static egress. |
| M7 | Medium | A signed-out user's access token stays valid until it expires (verification is stateless). Deleted accounts are blocked by a tombstone. | **Partly mitigated.** Set Supabase JWT expiry to 15 minutes. |
| M8 | Medium | The public `/health` endpoint returned raw database and Redis exception text, which can name hosts and users. Found while adding monitoring. | **Fixed** — `"error"` only; the reason goes to the logs. |
| L1 | Low | `SECRET_KEY` existed with a guessable default and was used for nothing. | **Fixed** — removed. |
| L2 | Low | CORS allowed credentials although the API uses bearer tokens, never cookies. | **Fixed** — off. |
| L3 | Low | Responses carrying account data were cacheable by intermediaries. | **Fixed** — `Cache-Control: no-store`. |
| L4 | Low | Android device backups included app data. | **Fixed** — `allowBackup: false`. |
| L5 | Low | python-dotenv 1.0.1 advisory (symlink following in `set_key`, a path the app never calls). | **Fixed** — 1.2.4. |
| L6 | Low | Sandbox purchases grant access, so TestFlight testers can get premium free. Needed: App Review buys with sandbox accounts against production builds. | **Accepted** — subscriptions record `is_sandbox`; review it before widening TestFlight. |
| L7 | Low | No certificate pinning. | **Accepted** at MASVS L1: HTTPS is enforced in release builds and by iOS ATS. |
| L8 | Low | Google sign-in on iOS needs Supabase's "skip nonce check", weakening replay protection for Google ID tokens (≈1 hour). Apple sign-in keeps full nonce checking. | **Accepted**, documented. |

Verified clean: full git history (no keys, tokens or credential files), release
bundles (CI rejects backend secret names, and a normal bundle must not contain
the e2e sign-in form), log redaction of credential and PII keys.

### C2: web dashboard sign-in

`AUTH_REQUIRED` must be `true`, or the paywall and per-team ownership can be
bypassed by calling the API without a token. Of the options (add sign-in to the
web, retire it, or limit it to free data), sign-in was chosen:

- Apple or Google through Supabase's OAuth redirect with PKCE, so the redirect
  carries a one-time code, never tokens. Supabase only redirects to URLs on its
  allowlist.
- The team comes from the account (`/me`), not from user input; connecting one
  uses the same team-name code as the app. Access is the server's
  `/me/entitlements`; the page only chooses which screen to show.
- Subscriptions are sold only in the app. A web user without access is told to
  subscribe there; the web takes no payments.
- The browser session lives in `localStorage`, as it must without a server.
  Any script running on the page could read it, so the site sends a
  Content-Security-Policy: scripts from this origin only, and `connect-src`
  limited to this site, the API and Supabase, so even injected script cannot
  post a token elsewhere. Inline scripts are allowed because the page is
  statically prerendered (nonces would force every request to render
  dynamically). Framing is refused.
- A 401 from the API signs the browser out locally.

### OWASP API Security Top 10

| Risk | Control |
|---|---|
| API1 Broken object level authorisation | Every `/{manager_id}` route requires ownership (`ManagerAccess`); structural test fails on any route without it. |
| API2 Broken authentication | Supabase tokens verified locally: algorithm pinned per key type, issuer, audience, expiry; anon/service keys and anonymous sessions rejected. |
| API3 Property level authorisation / mass assignment | Write bodies use Pydantic models with `extra="forbid"`; server derives user, plan and entitlement itself. |
| API4 Unrestricted resource consumption | Per-user/IP rate limits by tier, 1 MB body limit, optimiser endpoints on the strictest tier. |
| API5 Function level authorisation | Operator routes need `X-Job-Token` and fail closed in production; structural test covers every write route. |
| API6 Sensitive business flows | Team ownership proved by a code in the FPL team name; one trial per user and per team, ever; tombstones on deletion. |
| API7 SSRF | No user-supplied URLs are fetched; FPL, RevenueCat, Supabase and Expo hosts are fixed. |
| API8 Security misconfiguration | Production self-check, docs off, strict headers, no credentialed CORS. |
| API9 Improper inventory | Single API version; schema not published in production; route walker test. |
| API10 Unsafe consumption of APIs | Webhooks authenticated and only used as a cue to re-read from RevenueCat; store state never taken from the client. |

### OWASP MASVS (mobile)

| Area | Control |
|---|---|
| Storage | Session sealed with AES-GCM; key in Keychain / Keystore, device-only; no plaintext tokens; backups off. |
| Crypto | Platform AES-GCM via expo-crypto; no custom crypto. |
| Auth | Native Apple/Google sign-in exchanged with Supabase; access decided only by the server. |
| Network | HTTPS-only release builds; ATS on iOS; no pinning (L7). |
| Platform | Deep links pass through the same access gate; destructive actions need confirmation; no WebViews. |
| Code | Dependency audits in CI; no secrets in the bundle. |
| Privacy | Minimal PII (no email/phone stored by the backend); account deletion removes personal data. Crash and error reports (Sentry) carry no user identity, IP, request bodies, local variables or screenshots; see OBSERVABILITY.md. |

### Before release (security)

- [ ] Run all Alembic migrations on Supabase, then confirm in Supabase's
      Security Advisor that no public table lacks RLS, and that
      `curl "$SUPABASE_URL/rest/v1/users" -H "apikey: <publishable key>"` is refused.
- [ ] Vercel: set `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_KEY`
      (publishable key) and redeploy **before** the backend deploys with
      `AUTH_REQUIRED=true`. Confirm the production response carries the
      `Content-Security-Policy` header.
- [ ] Supabase → Authentication → URL Configuration: the web site's URL as the
      Site URL and in Redirect URLs (plus `http://localhost:3001` for
      development). Apple sign-in on the web needs an Apple **Services ID**
      with Supabase's callback URL as its return URL.
- [ ] Set in production: `JOB_TOKEN`, `REVENUECAT_WEBHOOK_AUTH`,
      `REVENUECAT_WEBHOOK_SIGNING_SECRET`, `EXPO_ACCESS_TOKEN` (enhanced push
      security on), `SUPABASE_SERVICE_KEY`, `TRUSTED_PROXY_HOPS=1`. Startup
      logs `security self-check:` errors for anything missing.
- [ ] Supabase: JWT expiry 15 min; email sign-in off in production; Apple and
      Google providers configured.
- [ ] RevenueCat: Restore Behavior "transfer if no active subscriptions".
- [ ] Monitoring (OBSERVABILITY.md): `SENTRY_DSN` on Render,
      `EXPO_PUBLIC_SENTRY_DSN` in EAS, `SENTRY_AUTH_TOKEN` in EAS as a
      sensitive variable only, `HEALTHCHECKS_PING_URL` on Render. Set a
      per-key rate limit on each Sentry project.
- [ ] Check first-deploy logs for distinct client IPs (H4).
- [ ] Re-run `pip-audit` and `npm audit` (CI does) and this review on major
      dependency upgrades.
