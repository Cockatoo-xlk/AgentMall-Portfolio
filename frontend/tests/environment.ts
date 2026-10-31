/** Only process-local numeric ports vary; every E2E target stays on loopback. */
function port(name: string, fallback: number) {
  const raw = process.env[name] ?? String(fallback)
  if (!/^\d{1,5}$/.test(raw) || Number(raw) < 1024 || Number(raw) > 65535)
    throw new Error(`Invalid isolated E2E port: ${name}`)
  return Number(raw)
}
export const MANAGED_DEMO = process.env.AGENTMALL_E2E_MANAGED_DEMO === '1'
export const API_PORT = port('AGENTMALL_E2E_API_PORT', MANAGED_DEMO ? 8015 : 8001)
export const WEB_PORT = port('AGENTMALL_E2E_WEB_PORT', MANAGED_DEMO ? 5185 : 5174)
if (MANAGED_DEMO && (API_PORT !== 8015 || WEB_PORT !== 5185))
  throw new Error('Managed demo must use its owned Compose ports')
if (API_PORT === WEB_PORT) throw new Error('Distinct isolated E2E ports required')
export const API_ORIGIN = `http://127.0.0.1:${API_PORT}`
export const WEB_ORIGIN = `http://127.0.0.1:${WEB_PORT}`
