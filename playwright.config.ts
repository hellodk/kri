import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  // Seeds an enabled salt-master + a group-with-creds + baseline nodes so the
  // bootstrap flow and fleet table/filter specs have the state they assume (#905).
  globalSetup: './tests/e2e/global-setup.ts',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // One retry on CI (not two): the suite runs serially with a 25-min job cap, and
  // each retry re-runs the spec's beforeEach (another login). Two retries on a
  // broadly-failing run compounded login volume and blew past the cap before the
  // suite finished, yielding no pass/fail signal (#905). One retry still absorbs
  // genuine UI flakiness while keeping the run inside the cap.
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['line'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: 'http://localhost',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
})
