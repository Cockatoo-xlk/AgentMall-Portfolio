import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30000,
  reporter: [['list'], ['json', { outputFile: 'test-results/results.json' }]],
  use: {
    baseURL: 'http://127.0.0.1:5174',
    trace: 'off',
    video: 'off',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: '../backend/.venv/bin/python ../backend/tests/web_e2e_server.py --port 8001',
      url: 'http://127.0.0.1:8001/openapi.json',
      reuseExistingServer: false,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 10000 },
      timeout: 60000,
    },
    {
      command: 'npm run dev -- --port 5174 --strictPort',
      url: 'http://127.0.0.1:5174',
      env: { AGENTMALL_API_TARGET: 'http://127.0.0.1:8001', VITE_AGENT_MODE: 'fixture' },
      reuseExistingServer: false,
    },
  ],
})
