import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API only allows the Vite dev origins on port 5173 (CORS), so the port is fixed.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  preview: { port: 4173, strictPort: true },
})
