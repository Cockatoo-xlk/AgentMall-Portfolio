import { defineConfig, devices } from '@playwright/test'
import { API_ORIGIN, API_PORT, WEB_ORIGIN, WEB_PORT, MANAGED_DEMO, PLAYGROUND_TEST } from './tests/environment.ts'
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30000,
  reporter: [['list'], ['json', { outputFile: 'test-results/results.json' }]],
  use: {
    baseURL: WEB_ORIGIN,
    trace: 'off',
    video: 'off',
    screenshot: 'only-on-failure',
  },
  // Native macOS shell probe had zero animation frames; full Chromium stays headless.
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], ...(MANAGED_DEMO || PLAYGROUND_TEST ? { channel: 'chromium' } : {}) } }],
  // Native browser/driver can use a newly owned container server without moving
  // the guarded PostgreSQL/Checkpoint connection or sharing any existing demo.
  webServer: PLAYGROUND_TEST ? [{
    command: 'docker compose -p agentmall-t15-a-tests -f ../compose.ci.yaml -f ../compose.playground-tests.yaml run --no-deps --name agentmall-t15-a-native-api --rm runner python scripts/playground_test_server.py',
    url: `${API_ORIGIN}/openapi.json`,
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 20000 },
    timeout: 60000,
  }, {
    command: `npm run dev -- --port ${WEB_PORT} --strictPort`,
    url: WEB_ORIGIN,
    env: { AGENTMALL_API_TARGET: API_ORIGIN },
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 10000 },
  }] : MANAGED_DEMO ? [{
    command: 'docker compose -p agentmall-t14-p1 -f ../compose.ci.yaml -f ../compose.cart-local.yaml run --no-deps --name agentmall-t14-p1-native-servers --rm runner python scripts/demo.py --catalog-profile legacy --seconds 600',
    url: WEB_ORIGIN,
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 15000 },
    timeout: 60000,
  }] : [
    {
      command: `../backend/.venv/bin/python ../backend/tests/web_e2e_server.py --port ${API_PORT}`,
      url: `${API_ORIGIN}/openapi.json`,
      reuseExistingServer: false,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 10000 },
      timeout: 60000,
    },
    {
      command: `npm run dev -- --port ${WEB_PORT} --strictPort`,
      url: WEB_ORIGIN,
      env: { AGENTMALL_API_TARGET: API_ORIGIN, VITE_AGENT_MODE: 'fixture' },
      reuseExistingServer: false,
    },
  ],
})
