import {defineConfig, devices} from '@playwright/test';

// End-to-end tests (chapter 14.9). With KEEL_E2E_BASE_URL set, the specs run
// against a running `keel serve` (CI starts it with the mock provider).
// Without it, Playwright serves the built front-end with `vite preview`.
const baseUrl = process.env['KEEL_E2E_BASE_URL'] ?? 'http://127.0.0.1:4173';
const isCi = process.env['CI'] !== undefined;
// Against keel serve, every answer runs the real retrieval with the pinned
// models on the CPU: 1 worker, so the questions do not queue behind the
// retrieval lock, and a longer wait for each expected state.
const isLive = process.env['KEEL_E2E_BASE_URL'] !== undefined;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  ...(isLive ? {workers: 1, expect: {timeout: 30_000}, timeout: 120_000} : {}),
  forbidOnly: isCi,
  retries: isCi ? 1 : 0,
  reporter: isCi ? [['list'], ['html', {open: 'never'}]] : 'list',
  use: {
    baseURL: baseUrl,
    trace: 'retain-on-failure',
  },
  // The admin jobs that change the index (ops-jobs.spec.ts) run last, in
  // their own project, so the other specs see the mini corpus unchanged.
  projects: [
    {
      name: 'desktop',
      use: {...devices['Desktop Chrome']},
      testIgnore: /ops-jobs\.spec\.ts/,
    },
    {
      name: 'phone',
      use: {...devices['Pixel 7']},
      testIgnore: /ops-jobs\.spec\.ts/,
    },
    {
      name: 'ops-jobs',
      use: {...devices['Desktop Chrome']},
      testMatch: /ops-jobs\.spec\.ts/,
      dependencies: ['desktop', 'phone'],
    },
  ],
  // Without KEEL_E2E_BASE_URL, serve the built page with vite preview.
  ...(!isLive
    ? {
        webServer: {
          command:
            'npm run preview -- --host 127.0.0.1 --port 4173 --strictPort',
          url: 'http://127.0.0.1:4173',
          reuseExistingServer: !isCi,
        },
      }
    : {}),
});
