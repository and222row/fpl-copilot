import { AESEncryptionKey, AESSealedData, aesDecryptAsync, aesEncryptAsync } from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import Storage from 'expo-sqlite/kv-store';

// The Supabase session (access + refresh token) must never sit in plain
// storage, but it can exceed the ~2 KB some iOS versions accept in the
// Keychain. So only a 256-bit AES key lives in the Keychain / Android
// Keystore, and the session is stored AES-GCM sealed in SQLite.
//
// THIS_DEVICE_ONLY keeps the key out of iCloud backups and device transfers;
// AFTER_FIRST_UNLOCK lets the token refresh while the app is backgrounded.

const KEY_NAME = 'fplc.session-key.v1';

let keyPromise: Promise<AESEncryptionKey> | null = null;

async function loadOrCreateKey(): Promise<AESEncryptionKey> {
  const stored = await SecureStore.getItemAsync(KEY_NAME);
  if (stored) return AESEncryptionKey.import(stored, 'base64');
  const key = await AESEncryptionKey.generate(256);
  await SecureStore.setItemAsync(KEY_NAME, await key.encoded('base64'), {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });
  return key;
}

function getKey(): Promise<AESEncryptionKey> {
  // Memoised so two concurrent first reads cannot each mint a different key.
  keyPromise ??= loadOrCreateKey().catch((e) => {
    keyPromise = null;
    throw e;
  });
  return keyPromise;
}

// expo-crypto takes string input as base64. These convert UTF-8 text (names in
// the session can be non-ASCII) to and from base64 via Latin-1 binary strings.
export function utf8ToBase64(text: string): string {
  return btoa(unescape(encodeURIComponent(text)));
}

export function base64ToUtf8(b64: string): string {
  return decodeURIComponent(escape(atob(b64)));
}

export const encryptedStorage = {
  async getItem(name: string): Promise<string | null> {
    const sealed = await Storage.getItemAsync(name);
    if (!sealed) return null;
    try {
      const plaintext = await aesDecryptAsync(AESSealedData.fromCombined(sealed), await getKey(), {
        output: 'base64',
        additionalData: utf8ToBase64(name),
      });
      return base64ToUtf8(plaintext);
    } catch {
      // Tampered, moved from another entry, or the key is gone (reinstall,
      // restored backup). Treat as signed out rather than crash.
      await Storage.removeItemAsync(name);
      return null;
    }
  },

  async setItem(name: string, value: string): Promise<void> {
    // The entry name is authenticated data, so a sealed value copied under a
    // different name fails to decrypt.
    const sealed = await aesEncryptAsync(utf8ToBase64(value), await getKey(), {
      additionalData: utf8ToBase64(name),
    });
    await Storage.setItemAsync(name, await sealed.combined('base64'));
  },

  async removeItem(name: string): Promise<void> {
    await Storage.removeItemAsync(name);
  },
};
