import * as Sentry from '@sentry/react-native';
import Constants from 'expo-constants';

// Crash and error reporting through Sentry (free Developer plan).
//
// Off unless EXPO_PUBLIC_SENTRY_DSN is set, and always off in development and
// in e2e builds, so only real users' crashes are reported. The DSN is public
// by design: it lets the app send events and nothing else.
//
// What leaves the device is kept to crash diagnostics: no user identity, no
// IP address, no screenshots or view hierarchy, no request bodies, and no
// console output. Events are therefore "not linked to the user" for the App
// Store privacy label and Google Play's data safety form.

// Inlined at build time, so these are fixed per bundle.
const dsn = process.env.EXPO_PUBLIC_SENTRY_DSN ?? '';
const e2e = process.env.EXPO_PUBLIC_E2E === 'true';

export function shouldEnable(build: { dsn: string; dev: boolean; e2e: boolean }): boolean {
  return Boolean(build.dsn) && !build.dev && !build.e2e;
}

export function monitoringEnabled(): boolean {
  return shouldEnable({ dsn, dev: __DEV__, e2e });
}

// Query strings are dropped from any URL: none should carry anything
// sensitive, but nothing in them is needed to debug a crash either.
function stripQuery(url: unknown): unknown {
  return typeof url === 'string' ? url.split('?')[0] : url;
}

export function scrubEvent<T extends Sentry.Event>(event: T): T {
  delete event.user;
  if (event.request) {
    delete event.request.data;
    delete event.request.cookies;
    delete event.request.headers;
    event.request.url = stripQuery(event.request.url) as string | undefined;
    delete event.request.query_string;
  }
  return event;
}

export function scrubBreadcrumb(crumb: Sentry.Breadcrumb): Sentry.Breadcrumb | null {
  // Console output is the one place app code might print something personal.
  if (crumb.category === 'console') return null;
  if (crumb.data && 'url' in crumb.data) {
    crumb.data = { ...crumb.data, url: stripQuery(crumb.data.url) };
  }
  return crumb;
}

export function initMonitoring(): void {
  if (!monitoringEnabled()) return;
  Sentry.init(
    sentryOptions(dsn, (Constants.expoConfig?.extra?.sentryEnvironment as string | undefined) ?? 'production'),
  );
}

export function sentryOptions(dsn: string, environment: string): Sentry.ReactNativeOptions {
  return {
    dsn,
    environment,
    sendDefaultPii: false,
    attachScreenshot: false,
    attachViewHierarchy: false,
    enableCaptureFailedRequests: false,
    // Errors only; performance tracing would eat the free quota.
    tracesSampleRate: 0,
    // Session counts give the crash-free rate. They carry no identity.
    enableAutoSessionTracking: true,
    beforeSend: (event) => scrubEvent(event),
    beforeBreadcrumb: (crumb) => scrubBreadcrumb(crumb),
  };
}

export function reportError(error: unknown): void {
  if (monitoringEnabled()) Sentry.captureException(error);
}

export const wrapRoot = Sentry.wrap;
