import { Platform } from 'react-native';
import Purchases, { PURCHASES_ERROR_CODE, type PurchasesPackage } from 'react-native-purchases';

import { config } from '@/lib/config';

// The store takes the payment and RevenueCat validates it. Whether that buys
// access is decided by the server, which this module never tells anything:
// after a purchase the app asks the server to check with RevenueCat itself.

let configured = false;

function apiKey(): string {
  if (Platform.OS === 'ios') return config.revenuecatIosKey;
  if (Platform.OS === 'android') return config.revenuecatAndroidKey;
  return '';
}

export function billingAvailable(): boolean {
  if (configured) return true;
  const key = apiKey();
  if (!key) return false;
  Purchases.configure({ apiKey: key });
  configured = true;
  return true;
}

/**
 * Tie purchases to the signed-in account. The RevenueCat customer id is the
 * Supabase user id, which is what the server looks up.
 */
export async function identifyBillingUser(userId: string): Promise<void> {
  if (!billingAvailable()) return;
  if ((await Purchases.getAppUserID()) !== userId) await Purchases.logIn(userId);
}

export async function resetBillingUser(): Promise<void> {
  if (!configured) return;
  // logOut rejects when the current customer is already anonymous.
  await Purchases.logOut().catch(() => undefined);
}

export interface Plans {
  monthly: PurchasesPackage | null;
  annual: PurchasesPackage | null;
  /** Whole-percent saving of annual over twelve months of monthly, or null. */
  annualSavingPercent: number | null;
}

export function annualSaving(monthlyPrice: number, annualPrice: number): number | null {
  if (monthlyPrice <= 0 || annualPrice <= 0) return null;
  const saving = Math.round((1 - annualPrice / (monthlyPrice * 12)) * 100);
  return saving > 0 ? saving : null;
}

/** Prices come from the store, localised, never from the app. */
export async function loadPlans(): Promise<Plans> {
  const offering = (await Purchases.getOfferings()).current;
  const monthly = offering?.monthly ?? null;
  const annual = offering?.annual ?? null;
  return {
    monthly,
    annual,
    annualSavingPercent:
      monthly && annual ? annualSaving(monthly.product.price, annual.product.price) : null,
  };
}

export type PurchaseOutcome = 'purchased' | 'cancelled' | 'pending';

export async function purchase(pkg: PurchasesPackage, userId: string): Promise<PurchaseOutcome> {
  await identifyBillingUser(userId);
  try {
    await Purchases.purchasePackage(pkg);
    return 'purchased';
  } catch (e) {
    const err = e as { code?: string; userCancelled?: boolean | null };
    if (err.code === PURCHASES_ERROR_CODE.PURCHASE_CANCELLED_ERROR || err.userCancelled) return 'cancelled';
    // Ask to Buy and slow payment methods: the store finishes it later and
    // the webhook grants access when it does.
    if (err.code === PURCHASES_ERROR_CODE.PAYMENT_PENDING_ERROR) return 'pending';
    throw e;
  }
}

export async function restore(userId: string): Promise<void> {
  await identifyBillingUser(userId);
  await Purchases.restorePurchases();
}

/** The store's own subscription page, where users cancel or change plan. */
export async function openManageSubscription(): Promise<void> {
  if (!billingAvailable()) return;
  await Purchases.showManageSubscriptions();
}
