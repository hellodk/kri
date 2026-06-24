/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'fs'
import { resolve } from 'path'

function readVersion(): string {
  // Local dev: VERSION is one level up from frontend/
  // Docker build: VERSION is copied into the same WORKDIR as frontend/
  for (const p of [resolve(__dirname, '..', 'VERSION'), resolve(__dirname, 'VERSION')]) {
    try { return readFileSync(p, 'utf-8').trim() } catch { /* try next */ }
  }
  return process.env.VITE_APP_VERSION ?? '0.0.0'
}

const APP_VERSION = readVersion()

export default defineConfig({
  plugins: [react()],
  define: {
    // Replaced at build time — use as: declare const __APP_VERSION__: string
    __APP_VERSION__: JSON.stringify(APP_VERSION),
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
  },
})
