# FPL Copilot — web dashboard

Next.js 16 dashboard for signed-in users with access. It signs in with
Supabase (the same accounts as the app), takes the team from the account, and
shows the same advice as the app. It sells nothing: users without access are
sent to the app to subscribe.

```bash
npm install
cp .env.example .env.local   # API URL and Supabase publishable key
npm run dev                  # http://localhost:3000
```

Checks: `npm run lint`, `npm run build`, `npx tsc --noEmit` (after a build).

This Next.js version differs from older ones; read the matching guide in
`node_modules/next/dist/docs/` before changing framework code (see
`AGENTS.md`).

More: [README](../README.md), [docs/AUTHENTICATION.md](../docs/AUTHENTICATION.md),
[docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).
