// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require("eslint-config-expo/flat");

module.exports = defineConfig([
  expoConfig,
  {
    ignores: ["dist/*"],
  },
  {
    // jest.mock calls must precede the imports they replace, and
    // jest.isolateModules needs require() to load a fresh module copy.
    files: ["**/__tests__/**"],
    rules: {
      "import/first": "off",
      "@typescript-eslint/no-require-imports": "off",
    },
  },
]);
