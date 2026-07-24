import { access, copyFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const source = path.resolve('data', 'example-days.json');
const destination = path.resolve('data', 'days.json');
const force = process.argv.includes('--force');

await mkdir(path.dirname(destination), { recursive: true });
if (!force) {
  try {
    await access(destination);
    console.error('data/days.json already exists. Re-run with --force to replace it with the synthetic example.');
    process.exit(1);
  } catch {
    // The destination does not exist, so creating it is safe.
  }
}
await copyFile(source, destination);
console.log('Seeded data/days.json with the synthetic five-node example.');
