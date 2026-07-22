import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './specs',
  testMatch: 'twm_demo_workflow.spec.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 12 * 60 * 1000,
  reporter: [['list']],
  use: {
    baseURL: process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{
    name: 'chromium',
    use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 } },
  }],
});
