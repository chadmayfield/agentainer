import { defineConfig } from '@playwright/test';
import path from 'node:path';

export default defineConfig({
  testDir: '.',
  testMatch: 'screenshots.spec.ts',
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 90_000,
  outputDir: path.resolve(__dirname, '../../artifacts/visual/playwright'),
  reporter: 'list',
  use: {
    browserName: 'chromium',
    channel: process.env.BROWSER_CHANNEL || undefined,
    headless: true,
    viewport: { width: 1400, height: 900 },
    deviceScaleFactor: 1,
    locale: 'en-US',
    timezoneId: 'UTC',
  },
});
