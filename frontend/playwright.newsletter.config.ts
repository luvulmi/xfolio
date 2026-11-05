import { defineConfig } from '@playwright/test';
import integration from './playwright.integration.config';

export default defineConfig({
  ...integration,
  testDir: './tests/e2e/newsletter_api',
  webServer: {
    ...(integration.webServer as object),
    env: { ...process.env, XFOLIO_BROWSER_TEST_NEWSLETTER: 'true' },
  },
});
