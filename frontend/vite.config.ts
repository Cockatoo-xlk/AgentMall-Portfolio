import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    // Evidence writes must not reload the page and discard memory-only authentication.
    watch: { ignored: ['**/evidence/**', '**/test-results/**', '**/playwright-report/**'] },
    proxy: { '/api': process.env.AGENTMALL_API_TARGET ?? 'http://127.0.0.1:8000' },
  },
})
