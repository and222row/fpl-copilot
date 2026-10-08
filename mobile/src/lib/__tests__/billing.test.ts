jest.mock('react-native-purchases', () => ({
  __esModule: true,
  default: {
    configure: jest.fn(),
    getAppUserID: jest.fn(),
    logIn: jest.fn(),
    logOut: jest.fn(),
    getOfferings: jest.fn(),
    purchasePackage: jest.fn(),
    restorePurchases: jest.fn(),
    showManageSubscriptions: jest.fn(),
  },
  PURCHASES_ERROR_CODE: { PURCHASE_CANCELLED_ERROR: '1', PAYMENT_PENDING_ERROR: '20' },
}));
jest.mock('@/lib/config', () => ({ config: { revenuecatIosKey: 'appl_test', revenuecatAndroidKey: 'goog_test' } }));

const mockPurchases: Record<string, jest.Mock> = jest.requireMock('react-native-purchases').default;

import type { Entitlement } from '@/lib/api';
import { annualSaving, identifyBillingUser, loadPlans, purchase, resetBillingUser } from '@/lib/billing';
import { describeEntitlement, managedInStore } from '@/lib/subscription';

const USER = '11111111-1111-4111-8111-111111111111';
const pkg = (price: number, priceString: string) => ({ product: { price, priceString } }) as never;

beforeEach(() => {
  Object.values(mockPurchases).forEach((m) => m.mockReset());
  mockPurchases.getAppUserID.mockResolvedValue(USER);
  mockPurchases.logOut.mockResolvedValue({});
});

test('the annual saving is computed from store prices', () => {
  expect(annualSaving(3.99, 29.99)).toBe(37);
  expect(annualSaving(4.99, 39.99)).toBe(33);
  expect(annualSaving(3.99, 60)).toBeNull(); // annual dearer than monthly: no claim
  expect(annualSaving(0, 29.99)).toBeNull();
});

test('plans come from the current offering', async () => {
  mockPurchases.getOfferings.mockResolvedValue({
    current: { monthly: pkg(3.99, '€3.99'), annual: pkg(29.99, '€29.99') },
  });
  const plans = await loadPlans();
  expect(plans.annualSavingPercent).toBe(37);
  expect(plans.monthly).not.toBeNull();
});

test('a missing offering yields no plans rather than a crash', async () => {
  mockPurchases.getOfferings.mockResolvedValue({ current: null });
  expect(await loadPlans()).toEqual({ monthly: null, annual: null, annualSavingPercent: null });
});

test('purchases are made as the signed-in user, switching if needed', async () => {
  mockPurchases.getAppUserID.mockResolvedValue('$RCAnonymousID:abc');
  mockPurchases.purchasePackage.mockResolvedValue({});
  expect(await purchase(pkg(3.99, '€3.99'), USER)).toBe('purchased');
  expect(mockPurchases.logIn).toHaveBeenCalledWith(USER);
  expect(mockPurchases.logIn.mock.invocationCallOrder[0]).toBeLessThan(
    mockPurchases.purchasePackage.mock.invocationCallOrder[0],
  );
});

test('no re-login when already identified', async () => {
  await identifyBillingUser(USER);
  expect(mockPurchases.logIn).not.toHaveBeenCalled();
});

test.each([
  [{ code: '1' }, 'cancelled'],
  [{ userCancelled: true }, 'cancelled'],
  [{ code: '20' }, 'pending'],
])('store outcome %j maps to %s', async (error, outcome) => {
  mockPurchases.purchasePackage.mockRejectedValue(error);
  expect(await purchase(pkg(3.99, '€3.99'), USER)).toBe(outcome);
});

test('other store errors surface', async () => {
  mockPurchases.purchasePackage.mockRejectedValue(new Error('Store unavailable'));
  await expect(purchase(pkg(3.99, '€3.99'), USER)).rejects.toThrow('Store unavailable');
});

test('sign-out resets the RevenueCat customer and tolerates an anonymous one', async () => {
  await identifyBillingUser(USER);
  mockPurchases.logOut.mockRejectedValue(new Error('already anonymous'));
  await expect(resetBillingUser()).resolves.toBeUndefined();
});

const ent = (e: Partial<Entitlement>): Entitlement => ({
  premium: true, status: 'ACTIVE', plan: 'ANNUAL', provider: 'APPLE', trial_started_at: null,
  trial_ends_at: null, subscription_ends_at: '2027-10-08T00:00:00Z', ...e,
});

test('subscription wording follows the server status', () => {
  expect(describeEntitlement(ent({}))).toMatch(/^Annual plan · renews /);
  expect(describeEntitlement(ent({ status: 'CANCELED' }))).toMatch(/cancelled, access until/);
  expect(describeEntitlement(ent({ status: 'PAST_DUE', plan: 'MONTHLY' }))).toBe('Monthly plan · payment problem');
  expect(describeEntitlement(ent({ status: 'EXPIRED', premium: false }))).toBe('Subscription ended');
  expect(describeEntitlement(ent({ status: 'EXPIRED', provider: null, plan: null }))).toBe('Free trial ended');
  expect(describeEntitlement(ent({ status: 'NONE', provider: null }))).toBe('No subscription');
});

test('only live store subscriptions get a manage button', () => {
  expect(managedInStore(ent({}))).toBe(true);
  expect(managedInStore(ent({ provider: 'GOOGLE', status: 'PAST_DUE' }))).toBe(true);
  expect(managedInStore(ent({ status: 'EXPIRED' }))).toBe(false);
  expect(managedInStore(ent({ provider: 'TRIAL', status: 'TRIALING' }))).toBe(false);
});
