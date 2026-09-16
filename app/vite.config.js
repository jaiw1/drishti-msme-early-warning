import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base: './' keeps asset paths relative so the static build works on any host
// (Vercel/Netlify/subpath). The nginx deploy overrides it: `vite build --base /drishti/`.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    // Point the dev server at a local uvicorn so cookies stay same-origin and CSRF works.
    proxy: process.env.VITE_DEV_API_PROXY
      ? { '/api': { target: process.env.VITE_DEV_API_PROXY, changeOrigin: false } }
      : undefined,
  },
  test: {
    environment: 'jsdom',
    // An explicit origin: without one jsdom serves an opaque origin and localStorage
    // is undefined, which is not how any browser behaves.
    environmentOptions: { jsdom: { url: 'http://localhost:5173/' } },
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    css: false,
    include: ['src/**/*.test.{js,jsx}'],
    restoreMocks: true,
  },
})
