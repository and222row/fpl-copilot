import { GoogleSignin, isSuccessResponse } from '@react-native-google-signin/google-signin';
import type { Session } from '@supabase/supabase-js';
import * as AppleAuthentication from 'expo-apple-authentication';
import * as Crypto from 'expo-crypto';
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { Platform } from 'react-native';

import { identifyBillingUser, resetBillingUser } from '@/lib/billing';
import { config } from '@/lib/config';
import { queryClient } from '@/lib/query';
import { supabase } from '@/lib/supabase';

interface AuthContextValue {
  session: Session | null;
  loading: boolean;
  signInWithApple: () => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

let googleConfigured = false;
function configureGoogle() {
  if (googleConfigured) return;
  GoogleSignin.configure({
    // The web client ID is what Supabase validates the ID token's audience
    // against, even on iOS and Android.
    webClientId: config.googleWebClientId,
    iosClientId: config.googleIosClientId || undefined,
  });
  googleConfigured = true;
}

function isCancellation(e: unknown): boolean {
  const code = (e as { code?: string } | null)?.code;
  return code === 'ERR_REQUEST_CANCELED' || code === 'SIGN_IN_CANCELLED';
}

async function signInWithApple(): Promise<void> {
  // Apple signs a hash of the nonce into the identity token; Supabase checks
  // the raw value against it, so a captured token cannot be replayed.
  const rawNonce = Crypto.randomUUID() + Crypto.randomUUID();
  const hashedNonce = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    rawNonce,
  );
  try {
    const credential = await AppleAuthentication.signInAsync({
      requestedScopes: [
        AppleAuthentication.AppleAuthenticationScope.EMAIL,
        AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
      ],
      nonce: hashedNonce,
    });
    if (!credential.identityToken) throw new Error('Apple did not return an identity token.');
    const { error } = await supabase.auth.signInWithIdToken({
      provider: 'apple',
      token: credential.identityToken,
      nonce: rawNonce,
    });
    if (error) throw error;
  } catch (e) {
    if (isCancellation(e)) return;
    throw e;
  }
}

async function signInWithGoogle(): Promise<void> {
  configureGoogle();
  try {
    if (Platform.OS === 'android') {
      await GoogleSignin.hasPlayServices({ showPlayServicesUpdateDialog: true });
    }
    const response = await GoogleSignin.signIn();
    if (!isSuccessResponse(response)) return; // cancelled
    const idToken = response.data.idToken;
    if (!idToken) throw new Error('Google did not return an ID token.');
    const { error } = await supabase.auth.signInWithIdToken({ provider: 'google', token: idToken });
    if (error) throw error;
  } catch (e) {
    if (isCancellation(e)) return;
    throw e;
  }
}

async function signOut(): Promise<void> {
  // Global scope revokes every refresh token for this user on the server, not
  // just the copy on this device.
  await supabase.auth.signOut({ scope: 'global' });
  if (googleConfigured) await GoogleSignin.signOut().catch(() => undefined);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase.auth
      .getSession()
      .then(({ data }) => setSession(data.session))
      .finally(() => setLoading(false));

    const { data } = supabase.auth.onAuthStateChange((event, next) => {
      setSession(next);
      // Never let one account's cached squad or entitlement show to the next.
      if (event === 'SIGNED_OUT' || event === 'SIGNED_IN') queryClient.clear();
    });
    return () => data.subscription.unsubscribe();
  }, []);

  // Kept out of onAuthStateChange: Supabase warns that awaiting other work
  // inside that callback can deadlock its auth lock.
  const userId = session?.user.id;
  useEffect(() => {
    if (loading) return;
    (userId ? identifyBillingUser(userId) : resetBillingUser()).catch(() => undefined);
  }, [userId, loading]);

  return (
    <AuthContext.Provider value={{ session, loading, signInWithApple, signInWithGoogle, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>');
  return value;
}
