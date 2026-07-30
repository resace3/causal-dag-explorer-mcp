/**
 * Render the raster icons from `public/favicon.svg`.
 *
 * An SVG favicon alone is not enough. Chrome keeps a favicon *database* that
 * backs the bookmarks bar, Windows shortcuts want a real .ico, and iOS wants a
 * PNG of its own — so the one SVG is the source of truth and everything else is
 * generated from it rather than drawn twice and allowed to drift.
 *
 * Run: `npm run icons`
 */

import { chromium } from '@playwright/test';
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const publicDir = join(here, '..', 'public');

/** Sizes Chrome, Windows, iOS and the web manifest ask for. */
const PNG_SIZES = [16, 32, 48, 180, 192, 512];
const ICO_SIZES = [16, 32, 48];

async function render(browser, svg, size) {
  const page = await browser.newPage({
    viewport: { width: size, height: size },
    deviceScaleFactor: 1,
  });
  // The SVG is inlined rather than navigated to, so no file:// origin rules or
  // scrollbars can creep into the rendered pixels.
  await page.setContent(
    `<!doctype html><html><body style="margin:0;width:${size}px;height:${size}px">${svg}</body></html>`,
  );
  await page.locator('svg').evaluate((node, px) => {
    node.setAttribute('width', String(px));
    node.setAttribute('height', String(px));
  }, size);
  const buffer = await page.screenshot({ omitBackground: true });
  await page.close();
  return buffer;
}

/**
 * Pack PNGs into an .ico container.
 *
 * ICO entries may hold PNG data directly (Vista onwards, and every browser that
 * matters), which avoids hand-rolling a BMP encoder for what is fundamentally
 * the same image at three sizes.
 */
function buildIco(images) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // 1 = icon
  header.writeUInt16LE(images.length, 4);

  const directory = Buffer.alloc(16 * images.length);
  let offset = header.length + directory.length;

  images.forEach(({ size, data }, index) => {
    const at = index * 16;
    directory.writeUInt8(size >= 256 ? 0 : size, at); // 0 means 256
    directory.writeUInt8(size >= 256 ? 0 : size, at + 1);
    directory.writeUInt8(0, at + 2); // palette size
    directory.writeUInt8(0, at + 3); // reserved
    directory.writeUInt16LE(1, at + 4); // colour planes
    directory.writeUInt16LE(32, at + 6); // bits per pixel
    directory.writeUInt32LE(data.length, at + 8);
    directory.writeUInt32LE(offset, at + 12);
    offset += data.length;
  });

  return Buffer.concat([header, directory, ...images.map((image) => image.data)]);
}

const svg = await readFile(join(publicDir, 'favicon.svg'), 'utf8');
const browser = await chromium.launch();

const rendered = new Map();
for (const size of new Set([...PNG_SIZES, ...ICO_SIZES])) {
  rendered.set(size, await render(browser, svg, size));
}
await browser.close();

for (const size of PNG_SIZES) {
  const name =
    size === 180 ? 'apple-touch-icon.png' : `icon-${size}.png`;
  await writeFile(join(publicDir, name), rendered.get(size));
  console.log(`wrote ${name} (${size}×${size})`);
}

await writeFile(
  join(publicDir, 'favicon.ico'),
  buildIco(ICO_SIZES.map((size) => ({ size, data: rendered.get(size) }))),
);
console.log(`wrote favicon.ico (${ICO_SIZES.join(', ')})`);
