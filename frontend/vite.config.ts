import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: {
    // strictPort rather than the default fall-forward: the backend's CORS policy
    // names http://localhost:5173 explicitly, so silently starting on 5174 would
    // trade a clear "port in use" error for a confusing wall of CORS failures.
    port: 5173,
    strictPort: true,
  },
  build: {
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
})
