import { createApp } from './app.js';
import { DayStore, defaultStorePath } from '../storage/dayStore.js';

const port = Number(process.env.DAY_DIAGRAM_PORT ?? 3000);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('DAY_DIAGRAM_PORT must be an integer from 1024 to 65535');
const store = new DayStore(defaultStorePath());
createApp(store).listen(port, '127.0.0.1', () => {
  console.log(`[day-diagram] Website running at http://127.0.0.1:${port}`);
  console.log(`[day-diagram] Data file: ${store.filePath}`);
});
