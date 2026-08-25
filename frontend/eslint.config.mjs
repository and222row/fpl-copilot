import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // Downgraded from error, deliberately.
      //
      // This React Compiler rule flags any setState in an effect body. Two of
      // the places it fires here are not mistakes but requirements:
      //
      //   * reading localStorage for the saved team ID — unavailable during
      //     SSR, so it cannot happen anywhere but an effect;
      //   * `useEffect(() => setMounted(true), [])` in app/page.tsx — the
      //     guard that stops a locale-formatted date rendering on the server.
      //     Without it React bails out of hydration and silently strips every
      //     event handler on the page (see "beware hydration mismatches" in
      //     the README). Removing it reintroduces a bug that presents as a
      //     completely dead UI.
      //
      // The rest are fetch-on-mount effects that resolve after an await. Left
      // as warnings so they stay visible instead of failing CI on a pattern
      // the codebase uses on purpose.
      "react-hooks/set-state-in-effect": "warn",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
