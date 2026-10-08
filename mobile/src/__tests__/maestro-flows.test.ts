/// <reference types="node" />
// Maestro flows run only on a device against staging, so a renamed testID or
// reworded button would otherwise surface there, slowly. This checks every
// selector the flows use against the app source, in the normal test run.
import fs from 'fs';
import path from 'path';

const ROOT = path.resolve(__dirname, '../..');
const FLOWS = path.join(ROOT, '.maestro');
const SRC = path.join(ROOT, 'src');

function files(dir: string, ext: string[]): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e: fs.Dirent) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return e.name === '__tests__' ? [] : files(p, ext);
    return ext.some((x) => e.name.endsWith(x)) ? [p] : [];
  });
}

const source = files(SRC, ['.tsx', '.ts'])
  .map((f) => fs.readFileSync(f, 'utf8'))
  .join('\n')
  .replace(/&apos;/g, "'")
  .replace(/&quot;/g, '"');
const flows = files(FLOWS, ['.yaml']).filter((f) => !f.endsWith('config.yaml'));

const staticIds = new Set([...source.matchAll(/testID="([^"]+)"/g)].map((m) => m[1]));
const templatePrefixes = [...source.matchAll(/testID=\{`([^`$]+)\$\{/g)].map((m) => m[1]);

// Text the app builds at runtime, so it cannot appear verbatim in source:
// server messages, player names, and interpolated strings. Each is covered by
// a unit or render test of the code that produces it.
const DYNAMIC_TEXT = new Set([
  'Salah', // player data
  'No FPL team found.*', // API error detail (backend test_onboarding)
  'Annual plan · renews .*', // describeEntitlement (billing.test.ts)
  'Recommendation · 1 GW', // `Recommendation · {horizon} GW` (screens.test.tsx)
]);

function unquote(s: string): string {
  return s.trim().replace(/^["']|["']$/g, '');
}

function idsIn(flow: string): string[] {
  return [...flow.matchAll(/\bid:\s*("[^"]+"|'[^']+'|\S+)/g)].map((m) => unquote(m[1]));
}

// tapOn / assertVisible / assertNotVisible / visible / element given a bare string.
function textsIn(flow: string): string[] {
  return [
    ...flow.matchAll(/(?:tapOn|assertVisible|assertNotVisible|visible|notVisible|element):[ \t]*("[^"]+"|'[^']+'|[^\s{][^\n]*)$/gm),
  ]
    .map((m) => unquote(m[1]))
    .filter((t) => t && !t.endsWith('.yaml'));
}

const isPattern = (t: string) => /[.*\\[\]()+?^$|{}]/.test(t);

describe.each(flows.map((f) => [path.relative(FLOWS, f), f]))('%s', (_name, file) => {
  const flow = fs.readFileSync(file, 'utf8');

  test('declares the app id', () => {
    expect(flow).toMatch(/^appId: com\.fplcopilot\.app$/m);
  });

  test('every id exists in the app', () => {
    for (const id of idsIn(flow)) {
      // "player-row-.*" or "notify-price" against testID={`player-row-${...}`} / {`notify-${...}`}
      const prefix = id.replace(/\.\*$/, '');
      const known =
        staticIds.has(id) ||
        templatePrefixes.some((p) => (id.endsWith('.*') ? p === prefix : id.startsWith(p) && id.length > p.length));
      expect({ id, known }).toEqual({ id, known: true });
    }
  });

  test('every literal text appears in the app', () => {
    for (const text of textsIn(flow)) {
      if (DYNAMIC_TEXT.has(text)) continue;
      if (isPattern(text)) {
        // Check the literal head of a pattern, e.g. "No FPL team found" from "No FPL team found.*".
        const head = text.split(/[.*\\[(+?^$|{]/)[0].trim();
        if (head.length >= 4) expect({ text, found: source.includes(head) }).toEqual({ text, found: true });
        continue;
      }
      expect({ text, found: source.includes(text) }).toEqual({ text, found: true });
    }
  });

  test('referenced subflows exist', () => {
    for (const m of flow.matchAll(/(?:runFlow:|file:)\s*(\S+\.yaml)/g)) {
      expect(fs.existsSync(path.resolve(path.dirname(file), m[1]))).toBe(true);
    }
  });
});

test('flows were found', () => {
  expect(flows.length).toBeGreaterThan(10);
});
