import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:18443' } },
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], restoreMocks: true, exclude: ['e2e/**', 'e2e-live/**', 'e2e-newsletter-live/**', 'node_modules/**'] },
});
