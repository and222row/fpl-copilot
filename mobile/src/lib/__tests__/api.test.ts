const mockGetSession = jest.fn();
const mockSignOut = jest.fn();

jest.mock('@/lib/config', () => ({ config: { apiUrl: 'https://api.test' } }));
jest.mock('@/lib/supabase', () => ({
  supabase: { auth: { getSession: () => mockGetSession(), signOut: (o: unknown) => mockSignOut(o) } },
}));

import { ApiError, api, request } from '@/lib/api';

const fetchMock = jest.fn();
globalThis.fetch = fetchMock as unknown as typeof fetch;

function respond(status: number, body: unknown) {
  fetchMock.mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

function signedIn(token = 'access-123') {
  mockGetSession.mockResolvedValue({ data: { session: { access_token: token } } });
}

beforeEach(() => {
  fetchMock.mockReset();
  mockSignOut.mockReset();
  mockGetSession.mockReset();
  signedIn();
});

test('sends the access token as a bearer header to the versioned API', async () => {
  respond(200, { premium: true });
  await api.entitlements();
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe('https://api.test/api/v1/me/entitlements');
  expect(init.headers.Authorization).toBe('Bearer access-123');
});

test('sends no Authorization header when signed out', async () => {
  mockGetSession.mockResolvedValue({ data: { session: null } });
  respond(200, {});
  await request('/fpl/gameweek');
  expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
});

test('serialises JSON bodies', async () => {
  respond(202, { status: 'verification_required' });
  await api.startConnection(1234);
  const init = fetchMock.mock.calls[0][1];
  expect(init.method).toBe('POST');
  expect(init.headers['Content-Type']).toBe('application/json');
  expect(JSON.parse(init.body)).toEqual({ fpl_entry_id: 1234 });
});

test('a 402 carries the server code so the app can show the paywall', async () => {
  respond(402, { detail: { code: 'PREMIUM_REQUIRED', message: 'Trial ended', entitlement: {} } });
  await expect(api.recommendation(1)).rejects.toMatchObject({
    status: 402,
    code: 'PREMIUM_REQUIRED',
    message: 'Trial ended',
  });
});

test('plain string details become the message', async () => {
  respond(409, { detail: 'Disconnect your current FPL team before connecting another' });
  await expect(api.startConnection(1)).rejects.toMatchObject({
    status: 409,
    code: 'HTTP_409',
    message: 'Disconnect your current FPL team before connecting another',
  });
});

test.each([
  [429, 'RATE_LIMITED'],
  [500, 'SERVER'],
  [503, 'SERVER'],
])('status %i maps to %s', async (status, code) => {
  respond(status, null);
  await expect(request('/x')).rejects.toMatchObject({ status, code });
});

test('a rejected token signs the device out locally', async () => {
  respond(401, { detail: 'Token expired' });
  await expect(api.me()).rejects.toBeInstanceOf(ApiError);
  expect(mockSignOut).toHaveBeenCalledWith({ scope: 'local' });
});

test('a 401 without a token does not sign out', async () => {
  mockGetSession.mockResolvedValue({ data: { session: null } });
  respond(401, { detail: 'Not signed in' });
  await expect(api.me()).rejects.toBeInstanceOf(ApiError);
  expect(mockSignOut).not.toHaveBeenCalled();
});

test('network failure is reported as NETWORK', async () => {
  fetchMock.mockRejectedValueOnce(new TypeError('Network request failed'));
  await expect(api.me()).rejects.toMatchObject({ status: 0, code: 'NETWORK' });
});

test('a hung request times out', async () => {
  jest.useFakeTimers();
  fetchMock.mockImplementationOnce(
    (_url: string, init: { signal: AbortSignal }) =>
      new Promise((_resolve, reject) => {
        init.signal.addEventListener('abort', () => reject(new Error('aborted')));
      }),
  );
  const assertion = expect(request('/slow', { timeoutMs: 1000 })).rejects.toMatchObject({
    code: 'TIMEOUT',
  });
  await jest.advanceTimersByTimeAsync(1001);
  await assertion;
  jest.useRealTimers();
});

test('204 responses resolve to null', async () => {
  fetchMock.mockResolvedValueOnce({ ok: true, status: 204, json: async () => { throw new Error('no body'); } });
  await expect(api.disconnect(1)).resolves.toBeNull();
});
