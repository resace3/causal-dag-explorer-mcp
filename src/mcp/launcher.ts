import { spawn, type ChildProcess } from 'node:child_process';
import { createServer } from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

let child: ChildProcess | undefined;
let currentPort: number | undefined;

async function portIsFree(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = createServer();
    server.once('error', () => resolve(false));
    server.once('listening', () => server.close(() => resolve(true)));
    server.listen(port, '127.0.0.1');
  });
}

async function healthy(port: number): Promise<boolean> {
  try { return (await fetch(`http://127.0.0.1:${port}/health`)).ok; } catch { return false; }
}

export async function launch(preferredPort = 3000) {
  if (!Number.isInteger(preferredPort) || preferredPort < 1024 || preferredPort > 65535) throw new Error('port must be an integer from 1024 to 65535');
  if (currentPort && await healthy(currentPort)) return { status: 'running', url: `http://127.0.0.1:${currentPort}`, port: currentPort, reused: true };
  let port = preferredPort;
  while (port < preferredPort + 10 && !(await portIsFree(port))) {
    if (await healthy(port)) return { status: 'running', url: `http://127.0.0.1:${port}`, port, reused: true };
    port += 1;
  }
  if (!(await portIsFree(port))) throw new Error(`No available port found from ${preferredPort} to ${port}`);
  const here = path.dirname(fileURLToPath(import.meta.url));
  const serverEntry = path.resolve(here, '../server/index.js');
  child = spawn(process.execPath, [serverEntry], {
    cwd: path.resolve(here, '../../..'),
    env: { ...process.env, DAY_DIAGRAM_PORT: String(port) },
    shell: false,
    windowsHide: true,
    stdio: 'ignore'
  });
  currentPort = port;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (await healthy(port)) return { status: 'running', url: `http://127.0.0.1:${port}`, port, pid: child.pid, reused: false };
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  child.kill();
  child = undefined;
  currentPort = undefined;
  throw new Error('The website process started but did not pass its health check');
}
