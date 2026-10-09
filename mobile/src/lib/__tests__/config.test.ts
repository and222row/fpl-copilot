jest.mock('expo-constants', () => ({}));

// config.ts validates required values when imported; give it some.
process.env.EXPO_PUBLIC_API_URL = 'https://api.test';
process.env.EXPO_PUBLIC_SUPABASE_URL = 'https://x.supabase.co';
process.env.EXPO_PUBLIC_SUPABASE_KEY = 'sb_publishable_x';

const { checkStoreKey } = require('@/lib/config') as typeof import('@/lib/config');

const TEST_KEY = 'test_abc123';

describe('RevenueCat Test Store keys', () => {
  test('a release build refuses one', () => {
    expect(() => checkStoreKey('EXPO_PUBLIC_REVENUECAT_IOS_KEY', TEST_KEY, { dev: false, e2e: false })).toThrow(
      /Test Store key/,
    );
  });

  test('development and e2e builds may use one', () => {
    expect(checkStoreKey('K', TEST_KEY, { dev: true, e2e: false })).toBe(TEST_KEY);
    expect(checkStoreKey('K', TEST_KEY, { dev: false, e2e: true })).toBe(TEST_KEY);
  });

  test('store keys and an empty key pass in release builds', () => {
    expect(checkStoreKey('K', 'appl_abc', { dev: false, e2e: false })).toBe('appl_abc');
    expect(checkStoreKey('K', 'goog_abc', { dev: false, e2e: false })).toBe('goog_abc');
    expect(checkStoreKey('K', '', { dev: false, e2e: false })).toBe('');
  });
});
