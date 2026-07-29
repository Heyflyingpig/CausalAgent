import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e-mock',
  timeout: 60_000,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    channel: 'msedge',
    trace: 'retain-on-failure',
  },
})
