import path from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const port = Number(process.env.XFOLIO_BROWSER_TEST_PORT ?? '8447');
if (!Number.isInteger(port) || port < 1024 || port > 65535 || [3000, 8000].includes(port)) throw new Error('invalid_browser_test_port');
const origin = `https://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './tests/e2e/legacy_api',
  fullyParallel: false,
  workers: 1,
  globalTeardown: './tests/e2e/legacy_api/cleanup.ts',
  timeout: 30_000,
  use: { baseURL: origin, ignoreHTTPSErrors: true, trace: 'retain-on-failure' },
  projects: [{ name: 'live-api-chromium', use: process.env.CI ? { ...devices['Desktop Chrome'] } : { ...devices['Desktop Edge'], channel: 'msedge' } }],
  webServer: {
    command: 'uv run --no-sync --cache-dir .cache/uv python tests/support/browser_api_server.py',
    cwd: path.resolve(import.meta.dirname, '..'),
    url: origin,
    ignoreHTTPSErrors: true,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
