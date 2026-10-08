# FPL Copilot — mobile

iOS and Android app (Expo SDK 57, React Native, Expo Router). Full
documentation: [docs/MOBILE_APP.md](../docs/MOBILE_APP.md).

```bash
npm install
cp .env.example .env      # fill it in: docs/ENVIRONMENT_VARIABLES.md
npx expo run:android      # or run:ios on macOS; Expo Go is not supported
```

Checks: `npm run lint`, `npm run typecheck`, `npm test`, `npx expo-doctor`.

End-to-end tests (Maestro, against staging): [.maestro/README.md](.maestro/README.md).
