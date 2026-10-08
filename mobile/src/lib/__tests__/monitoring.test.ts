const mockInit = jest.fn();
const mockCapture = jest.fn();

jest.mock('@sentry/react-native', () => ({
  init: (o: unknown) => mockInit(o),
  captureException: (e: unknown) => mockCapture(e),
  wrap: (c: unknown) => c,
}));

import { initMonitoring, reportError, scrubBreadcrumb, scrubEvent, sentryOptions, shouldEnable } from '@/lib/monitoring';

const DSN = 'https://k@o0.ingest.sentry.io/1';

describe('when monitoring runs', () => {
  test.each([
    ['no DSN', { dsn: '', dev: false, e2e: false }, false],
    ['development', { dsn: DSN, dev: true, e2e: false }, false],
    ['e2e build', { dsn: DSN, dev: false, e2e: true }, false],
    ['release build with a DSN', { dsn: DSN, dev: false, e2e: false }, true],
  ])('%s', (_name, build, expected) => {
    expect(shouldEnable(build)).toBe(expected);
  });

  test('nothing is sent from the test run (a dev build)', () => {
    initMonitoring();
    reportError(new Error('x'));
    expect(mockInit).not.toHaveBeenCalled();
    expect(mockCapture).not.toHaveBeenCalled();
  });

  test('privacy options', () => {
    expect(sentryOptions(DSN, 'preview')).toMatchObject({
      dsn: DSN,
      environment: 'preview',
      sendDefaultPii: false,
      attachScreenshot: false,
      attachViewHierarchy: false,
      enableCaptureFailedRequests: false,
      tracesSampleRate: 0,
    });
  });
});

describe('what leaves the device', () => {
  test('events lose identity, headers, bodies and query strings', () => {
    const event = scrubEvent({
      user: { id: 'u1', email: 'a@b.c', ip_address: '1.2.3.4' },
      request: {
        url: 'https://api.test/me?code=123',
        headers: { Authorization: 'Bearer eyJ' },
        data: { fpl_entry_id: 1 },
        cookies: { a: 'b' },
        query_string: 'code=123',
      },
    });
    expect(event.user).toBeUndefined();
    expect(event.request).toEqual({ url: 'https://api.test/me' });
  });

  test('the configured hooks are the scrubbers', () => {
    const options = sentryOptions(DSN, 'production');
    const event = options.beforeSend!({ type: undefined, user: { id: 'u1' } }, {});
    expect(event).toEqual({ type: undefined });
    expect(options.beforeBreadcrumb!({ category: 'console', message: 'x' }, {})).toBeNull();
  });

  test('console breadcrumbs are dropped', () => {
    expect(scrubBreadcrumb({ category: 'console', message: 'token abc' })).toBeNull();
  });

  test('request breadcrumbs keep the path but not the query', () => {
    const crumb = scrubBreadcrumb({ category: 'fetch', data: { url: 'https://api.test/x?y=1', method: 'GET' } });
    expect(crumb?.data).toEqual({ url: 'https://api.test/x', method: 'GET' });
  });
});
