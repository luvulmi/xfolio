import path from 'node:path';
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e-live',
  fullyParallel: false,
  workers: 1,
  globalTeardown: './e2e-live/cleanup.ts',
  timeout: 30_000,
  use: { baseURL: 'https://127.0.0.1:8447', ignoreHTTPSErrors: true, trace: 'retain-on-failure' },
  projects: [{ name: 'live-api-chromium', use: process.env.CI ? { ...devices['Desktop Chrome'] } : { ...devices['Desktop Edge'], channel: 'msedge' } }],
  webServer: {
    command: 'uv run --no-sync --cache-dir .cache/uv python tests/support/browser_api_server.py',
    cwd: path.resolve(import.meta.dirname, '..'),
    url: 'https://127.0.0.1:8447',
    ignoreHTTPSErrors: true,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
