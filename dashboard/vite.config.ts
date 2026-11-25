import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dashboard is served by the Viber API at /dashboard/ and talks to that same origin.
// In `npm run dev` the API is proxied so no CORS setup is needed.
export default defineConfig({
  base: '/dashboard/',
  plugins: [react()],
  server: {
    proxy: {
      '/v1': 'http://localhost:8088',
      '/health': 'http://localhost:8088',
    },
  },
})
