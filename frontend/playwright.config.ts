import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  timeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:5177', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: process.env.CI ? { ...devices['Desktop Chrome'] } : { ...devices['Desktop Edge'], channel: 'msedge' } }],
  webServer: { command: 'npm run dev -- --port 5177 --strictPort', url: 'http://127.0.0.1:5177', reuseExistingServer: !process.env.CI },
});
