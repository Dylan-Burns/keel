import {defineConfig, devices} from '@playwright/test';

// End-to-end tests (chapter 14.9). With KEEL_E2E_BASE_URL set, the specs run
// against a running `keel serve` (CI starts it with the mock provider).
// Without it, Playwright serves the built front-end with `vite preview`.
const baseUrl = process.env['KEEL_E2E_BASE_URL'] ?? 'http://127.0.0.1:4173';
const isCi = process.env['CI'] !== undefined;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: isCi,
  retries: isCi ? 1 : 0,
  reporter: isCi ? [['list'], ['html', {open: 'never'}]] : 'list',
  use: {
    baseURL: baseUrl,
    trace: 'retain-on-failure',
  },
  projects: [
    {name: 'desktop', use: {...devices['Desktop Chrome']}},
    {name: 'phone', use: {...devices['Pixel 7']}},
  ],
  webServer:
    process.env['KEEL_E2E_BASE_URL'] === undefined
      ? {
          command: 'npm run preview -- --port 4173 --strictPort',
          url: 'http://127.0.0.1:4173',
          reuseExistingServer: !isCi,
        }
      : undefined,
});
