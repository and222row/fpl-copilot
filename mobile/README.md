# FPL Copilot — mobile

iOS and Android app (Expo SDK 57, React Native, Expo Router). It talks only to
the FastAPI backend and Supabase Auth; it holds no backend credentials.

## What exists

- Sign in with Apple (iOS) and Google (iOS + Android) through Supabase Auth.
- Session stored AES-GCM encrypted; the key is in the iOS Keychain / Android
  Keystore. Nothing sensitive is written to plain storage.
- Onboarding: Team ID → prove ownership with a code in the FPL team name →
  30-day trial starts.
- Paywall shown when the server says there is no entitlement. Purchase buttons
  are disabled until store billing is built.
- Home (gameweek, recommended action, captain, warnings, alerts) and Profile.

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
5. `cp .env.example .env` and fill it in.

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
- Only Home and Profile tabs exist; My Team, Transfers and Players come next.
- No in-app purchase yet; the paywall cannot take payment.
- `npm audit` reports high-severity issues in Expo's build tooling (node-forge,
  braces) and one moderate in `decode-uri-component`, which ships via
  expo-router. None has an upstream fix compatible with SDK 57; re-check before
  release.
