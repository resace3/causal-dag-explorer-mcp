import { access, readFile, readdir, stat } from 'node:fs/promises';
import path from 'node:path';

const required = [
  'README.md',
  'LICENSE',
  '.github/workflows/ci.yml',
  'docs/app-screenshot.jpg',
  'docs/architecture.jpg',
  'docs/architecture.svg',
  'data/example-days.json'
];
for (const file of required) await access(path.resolve(file));

const jpegSignature = Buffer.from([0xff, 0xd8, 0xff]);
for (const file of ['docs/app-screenshot.jpg', 'docs/architecture.jpg']) {
  const bytes = await readFile(path.resolve(file));
  if (bytes.length < 20_000 || !bytes.subarray(0, 3).equals(jpegSignature)) throw new Error(`${file} is not a valid release screenshot`);
}

const ignored = await readFile(path.resolve('.gitignore'), 'utf8');
if (!ignored.split(/\r?\n/).includes('data/days.json')) throw new Error('Runtime data/days.json must remain ignored');

const roots = ['src', 'tests', 'e2e', 'scripts', 'docs', 'data', '.github'];
const textExtensions = new Set(['.ts', '.tsx', '.js', '.mjs', '.json', '.md', '.yml', '.yaml', '.svg', '.html', '.css']);
const textFiles = ['README.md', 'LICENSE', '.gitignore'];

async function walk(directory) {
  for (const entry of await readdir(directory)) {
    const file = path.join(directory, entry);
    const info = await stat(file);
    if (info.isDirectory()) await walk(file);
    else if (textExtensions.has(path.extname(file))) textFiles.push(file);
  }
}
for (const root of roots) await walk(path.resolve(root));

const privateSensorFragment = ['nick', '_r'].join('');
const privatePathPattern = new RegExp(`C:\\\\${['Users', 'tabby'].join('\\\\')}`, 'i');
const forbidden = [
  { label: 'personal Windows path', pattern: privatePathPattern },
  { label: 'private HA entity fragment', pattern: new RegExp(privateSensorFragment, 'i') },
  { label: 'Home Assistant remote URL', pattern: /https:\/\/[^\s"']+\.ui\.nabu\.casa/i },
  { label: 'authorization header', pattern: /authorization\s*:\s*bearer\s+/i },
  { label: 'GitHub token', pattern: /gh[pousr]_[A-Za-z0-9_]{30,}/ }
];

for (const file of [...new Set(textFiles)]) {
  if (file.endsWith(path.join('data', 'days.json'))) continue;
  const content = await readFile(file, 'utf8');
  for (const item of forbidden) {
    if (item.pattern.test(content)) throw new Error(`${item.label} found in ${path.relative(process.cwd(), file)}`);
  }
}

const readme = await readFile(path.resolve('README.md'), 'utf8');
if (!readme.includes('docs/app-screenshot.jpg') || !readme.includes('docs/architecture.jpg')) throw new Error('README must embed both public screenshots');
console.log(`Release check passed: ${new Set(textFiles).size} text files scanned; runtime data remains excluded.`);
