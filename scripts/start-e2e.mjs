import { copyFile, mkdir } from 'node:fs/promises';
import path from 'node:path';

const directory = path.resolve('.tmp');
const dataFile = path.join(directory, 'playwright-days.json');
await mkdir(directory, { recursive: true });
await copyFile(path.resolve('data', 'example-days.json'), dataFile);
process.env.DAY_DIAGRAM_PORT = '3012';
process.env.DAY_DIAGRAM_DATA_FILE = dataFile;
await import('../dist/node/server/index.js');
