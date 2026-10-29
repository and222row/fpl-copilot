// Renders every logo file the project ships from the one design below.
//
//   node brand/render.mjs
//
// Uses the website's copy of sharp (cd frontend && npm ci first). The outputs
// are committed, so this only needs running again when the design changes.

import { createRequire } from "node:module";
import { rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const sharp = createRequire(join(root, "frontend", "package.json"))("sharp");

const PURPLE = "#37003C";

// ── The design ──────────────────────────────────────────────────────────────
// A football (white ring, rim patches) with a navigation arrow in the middle:
// football, plus something steering you. Drawn on a 1024 canvas around the
// centre so it can be scaled into each platform's safe area.

function pentagon(cx, cy, r, rotation) {
  return Array.from({ length: 5 }, (_, k) => {
    const a = ((rotation + 72 * k) * Math.PI) / 180;
    return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`;
  }).join(" ");
}

function mark({ arrowFill = "url(#arrow)", tint = 0.1 } = {}) {
  const patches = Array.from({ length: 5 }, (_, k) => {
    const a = ((-90 + 72 * k) * Math.PI) / 180;
    const x = 512 + 330 * Math.cos(a);
    const y = 512 + 330 * Math.sin(a);
    return `<polygon points="${pentagon(x, y, 92, 90 + 72 * k)}"/>`;
  }).join("");
  const arrow = [[0, -150], [115, 135], [0, 75], [-115, 135]]
    .map(([x, y]) => `${(512 + x * 1.1).toFixed(1)},${(525 + y * 1.1).toFixed(1)}`)
    .join(" ");
  return `
  <circle cx="512" cy="512" r="330" fill="#fff" fill-opacity="${tint}"/>
  <g clip-path="url(#ball)" fill="#fff" stroke="#fff" stroke-width="14" stroke-linejoin="round">${patches}</g>
  <circle cx="512" cy="512" r="330" fill="none" stroke="#fff" stroke-width="36"/>
  <polygon points="${arrow}" fill="${arrowFill}" stroke="${arrowFill}" stroke-width="33" stroke-linejoin="round"/>`;
}

const defs = `<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#5A0A63"/><stop offset="1" stop-color="#28002C"/>
  </linearGradient>
  <linearGradient id="arrow" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#04F5FF"/><stop offset="1" stop-color="#00FF87"/>
  </linearGradient>
  <clipPath id="ball"><circle cx="512" cy="512" r="330"/></clipPath>
</defs>`;

/** Background plus mark. `scale` shrinks the mark into a platform safe area. */
function svg({ background = true, withMark = true, radius = 0, scale = 1, markOptions } = {}) {
  const bg = background
    ? `<rect width="1024" height="1024" rx="${radius}" fill="url(#bg)"/>`
    : "";
  const t = `translate(${512 * (1 - scale)} ${512 * (1 - scale)}) scale(${scale})`;
  const fg = withMark ? `<g transform="${t}">${mark(markOptions)}</g>` : "";
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">${defs}${bg}${fg}</svg>`;
}

// ── Outputs ─────────────────────────────────────────────────────────────────

async function png(source, size, file, { flatten = false } = {}) {
  let image = sharp(Buffer.from(source)).resize(size, size);
  if (flatten) image = image.flatten({ background: PURPLE }); // stores reject alpha
  await image.png().toFile(join(root, file));
}

/** A .ico holding PNG images, which every current browser reads. */
async function ico(source, sizes, file) {
  const images = await Promise.all(
    sizes.map((s) => sharp(Buffer.from(source)).resize(s, s).png().toBuffer()),
  );
  const header = Buffer.alloc(6 + 16 * images.length);
  header.writeUInt16LE(1, 2); // type: icon
  header.writeUInt16LE(images.length, 4);
  let offset = header.length;
  images.forEach((data, i) => {
    const entry = 6 + 16 * i;
    header.writeUInt8(sizes[i] % 256, entry); // 0 means 256
    header.writeUInt8(sizes[i] % 256, entry + 1);
    header.writeUInt16LE(1, entry + 4); // colour planes
    header.writeUInt16LE(32, entry + 6); // bits per pixel
    header.writeUInt32LE(data.length, entry + 8);
    header.writeUInt32LE(offset, entry + 12);
    offset += data.length;
  });
  writeFileSync(join(root, file), Buffer.concat([header, ...images]));
}

const square = svg();
const rounded = svg({ radius: 224 });
// Android masks the adaptive foreground to a circle or squircle and may
// zoom it; only the middle 66 of 108 dp is guaranteed visible.
const adaptive = svg({ background: false, scale: 0.82 });
const monochrome = svg({ background: false, scale: 0.82, markOptions: { arrowFill: "#fff", tint: 0 } });

writeFileSync(join(root, "brand/logo.svg"), square);
writeFileSync(join(root, "frontend/src/app/icon.svg"), rounded);
writeFileSync(join(root, "frontend/public/logo.svg"), rounded);
await png(square, 120, "brand/google-oauth-logo.png", { flatten: true });
await png(square, 180, "frontend/src/app/apple-icon.png", { flatten: true });
await ico(rounded, [16, 32, 48], "frontend/src/app/favicon.ico");

await png(square, 1024, "mobile/assets/images/icon.png", { flatten: true });
await png(adaptive, 1024, "mobile/assets/images/android-icon-foreground.png");
await png(svg({ withMark: false }), 1024, "mobile/assets/images/android-icon-background.png");
await png(monochrome, 1024, "mobile/assets/images/android-icon-monochrome.png");
await png(svg({ background: false }), 512, "mobile/assets/images/splash-icon.png");
await png(rounded, 48, "mobile/assets/images/favicon.png");

// The template's Icon Composer bundle drew the Expo logo; iOS now uses icon.png.
rmSync(join(root, "mobile/assets/expo.icon"), { recursive: true, force: true });

console.log("Logo files written.");
