import { defineConfig } from '@playwright/test';
import integration from './playwright.integration.config';

export default defineConfig({
  ...integration,
  testDir: './e2e-newsletter-live',
  webServer: {
    ...(integration.webServer as object),
    env: { ...process.env, XFOLIO_BROWSER_TEST_NEWSLETTER: 'true' },
  },
});
