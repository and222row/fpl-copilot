import type { ExpoConfig } from 'expo/config';

// Permanent once the app is published to either store. Confirm before the
// first store build.
const BUNDLE_ID = 'com.fplcopilot.app';

// Uploads source maps and native debug symbols to Sentry during EAS builds.
// Only added when the build environment names the Sentry project, so a build
// without Sentry set up does not fail on the upload step. SENTRY_AUTH_TOKEN
// comes from the EAS environment (sensitive) and is never written here.
const sentryPlugin: [string, Record<string, string>][] =
  process.env.SENTRY_ORG && process.env.SENTRY_PROJECT
    ? [
        [
          '@sentry/react-native/expo',
          {
            organization: process.env.SENTRY_ORG,
            project: process.env.SENTRY_PROJECT,
            url: process.env.SENTRY_URL ?? 'https://sentry.io/',
          },
        ],
      ]
    : [];

const config: ExpoConfig = {
  name: 'FPL Copilot',
  slug: 'fpl-copilot',
  version: '1.0.0',
  orientation: 'portrait',
  icon: './assets/images/icon.png',
  scheme: 'fplcopilot',
  userInterfaceStyle: 'automatic',
  ios: {
    icon: './assets/expo.icon',
    bundleIdentifier: BUNDLE_ID,
    usesAppleSignIn: true,
  },
  android: {
    package: BUNDLE_ID,
    adaptiveIcon: {
      backgroundColor: '#E6F4FE',
      foregroundImage: './assets/images/android-icon-foreground.png',
      backgroundImage: './assets/images/android-icon-background.png',
      monochromeImage: './assets/images/android-icon-monochrome.png',
    },
    predictiveBackGestureEnabled: false,
    // The session is encrypted and its key never leaves the Keystore, but
    // nothing here needs backing up, so keep app data out of device backups.
    allowBackup: false,
  },
  web: {
    output: 'static',
    favicon: './assets/images/favicon.png',
  },
  plugins: [
    'expo-router',
    [
      'expo-splash-screen',
      {
        backgroundColor: '#37003C',
        image: './assets/images/splash-icon.png',
        imageWidth: 76,
      },
    ],
    'expo-secure-store',
    'expo-sqlite',
    'expo-apple-authentication',
    ['expo-notifications', { color: '#37003C' }],
    [
      '@react-native-google-signin/google-signin',
      {
        // The reversed iOS OAuth client ID. Not a secret.
        iosUrlScheme:
          process.env.GOOGLE_IOS_URL_SCHEME ?? 'com.googleusercontent.apps.SET_GOOGLE_IOS_URL_SCHEME',
      },
    ],
    ...sentryPlugin,
  ],
  experiments: {
    typedRoutes: true,
    reactCompiler: true,
  },
  extra: {
    // From `npx eas-cli@latest init`. Push tokens are issued per EAS project;
    // without it the app reports push as unavailable instead of failing.
    eas: { projectId: process.env.EAS_PROJECT_ID || undefined },
    // Tags crash reports with the EAS build profile (production, preview...).
    sentryEnvironment: process.env.EAS_BUILD_PROFILE ?? 'local',
  },
};

export default config;
