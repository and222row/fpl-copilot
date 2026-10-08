// expo-crypto, expo-secure-store and expo-sqlite are native modules, so they
// are replaced with in-memory fakes that keep the properties under test: a
// sealed value only opens with the same key AND the same associated data.

const mockKeychain = new Map<string, string>();
const mockKv = new Map<string, string>();
const mockSecureSetOptions: unknown[] = [];
let mockKeysGenerated = 0;

jest.mock('expo-secure-store', () => ({
  AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY: 'AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY',
  getItemAsync: async (k: string) => mockKeychain.get(k) ?? null,
  setItemAsync: async (k: string, v: string, o: unknown) => {
    mockSecureSetOptions.push(o);
    mockKeychain.set(k, v);
  },
}));

jest.mock('expo-sqlite/kv-store', () => ({
  __esModule: true,
  default: {
    getItemAsync: async (k: string) => mockKv.get(k) ?? null,
    setItemAsync: async (k: string, v: string) => void mockKv.set(k, v),
    removeItemAsync: async (k: string) => mockKv.delete(k),
  },
}));

jest.mock('expo-crypto', () => {
  class FakeKey {
    id: string;
    constructor(id: string) {
      this.id = id;
    }
    static async generate() {
      mockKeysGenerated += 1;
      return new FakeKey(`key-${mockKeysGenerated}`);
    }
    static async import(encoded: string) {
      return new FakeKey(atob(encoded));
    }
    async encoded() {
      return btoa(this.id);
    }
  }
  class FakeSealed {
    payload: { key: string; aad: string; data: string };
    constructor(payload: { key: string; aad: string; data: string }) {
      this.payload = payload;
    }
    static fromCombined(b64: string) {
      return new FakeSealed(JSON.parse(atob(b64)));
    }
    async combined() {
      return btoa(JSON.stringify(this.payload));
    }
  }
  const scramble = (s: string) => s.split('').reverse().join('');
  return {
    AESEncryptionKey: FakeKey,
    AESSealedData: FakeSealed,
    aesEncryptAsync: async (plain: string, key: FakeKey, o: { additionalData: string }) =>
      new FakeSealed({ key: key.id, aad: o.additionalData, data: scramble(plain) }),
    aesDecryptAsync: async (sealed: FakeSealed, key: FakeKey, o: { additionalData: string }) => {
      if (sealed.payload.key !== key.id || sealed.payload.aad !== o.additionalData) {
        throw new Error('GCM tag mismatch');
      }
      return scramble(sealed.payload.data);
    },
  };
});

type Storage = typeof import('@/lib/encrypted-storage');
let storage: Storage['encryptedStorage'];
let helpers: Storage;

const SESSION = JSON.stringify({ access_token: 'secret-access', refresh_token: 'secret-refresh' });

beforeEach(() => {
  mockKeychain.clear();
  mockKv.clear();
  mockSecureSetOptions.length = 0;
  mockKeysGenerated = 0;
  jest.isolateModules(() => {
    helpers = require('@/lib/encrypted-storage');
  });
  storage = helpers.encryptedStorage;
});

test('round-trips a session', async () => {
  await storage.setItem('sb-session', SESSION);
  expect(await storage.getItem('sb-session')).toBe(SESSION);
});

test('never writes the tokens to disk in clear', async () => {
  await storage.setItem('sb-session', SESSION);
  const onDisk = mockKv.get('sb-session')!;
  expect(onDisk).not.toContain('secret-refresh');
  expect(atob(onDisk)).not.toContain('secret-refresh');
});

test('the key lives in the mockKeychain, device-only', async () => {
  await storage.setItem('sb-session', SESSION);
  expect(mockKeychain.size).toBe(1);
  expect(mockSecureSetOptions[0]).toEqual({ keychainAccessible: 'AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY' });
});

test('concurrent first writes create exactly one key', async () => {
  await Promise.all([storage.setItem('a', '1'), storage.setItem('b', '2'), storage.getItem('c')]);
  expect(mockKeysGenerated).toBe(1);
  expect(await storage.getItem('a')).toBe('1');
  expect(await storage.getItem('b')).toBe('2');
});

test('reuses the stored key across app launches', async () => {
  await storage.setItem('sb-session', SESSION);
  jest.isolateModules(() => {
    helpers = require('@/lib/encrypted-storage');
  });
  expect(await helpers.encryptedStorage.getItem('sb-session')).toBe(SESSION);
  expect(mockKeysGenerated).toBe(1);
});

test('a value moved to another entry does not decrypt, and is discarded', async () => {
  await storage.setItem('sb-session', SESSION);
  mockKv.set('other', mockKv.get('sb-session')!);
  expect(await storage.getItem('other')).toBeNull();
  expect(mockKv.has('other')).toBe(false);
});

test('a lost key (reinstall, restored backup) reads as signed out', async () => {
  await storage.setItem('sb-session', SESSION);
  mockKeychain.clear();
  jest.isolateModules(() => {
    helpers = require('@/lib/encrypted-storage');
  });
  expect(await helpers.encryptedStorage.getItem('sb-session')).toBeNull();
});

test('missing entries are null and removal works', async () => {
  expect(await storage.getItem('nothing')).toBeNull();
  await storage.setItem('x', 'y');
  await storage.removeItem('x');
  expect(await storage.getItem('x')).toBeNull();
});

test('non-ASCII text survives the base64 conversion', () => {
  const text = 'Müller · Ødegaard ⚽ 日本';
  expect(helpers.base64ToUtf8(helpers.utf8ToBase64(text))).toBe(text);
});
