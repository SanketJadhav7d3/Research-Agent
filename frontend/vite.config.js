import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Serve `asset/` as the static root instead of the conventional `public/`.
  // Its contents are copied to the build output untouched, so the demo video
  // keeps its name and is served at /research-agent.mp4 — importing a 4MB file
  // through the bundler would hash it into the JS graph for no benefit.
  publicDir: 'asset',
  server: {
    port: 5173,
    // Local dev only. In Docker, nginx does this proxying instead.
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND_URL || 'http://localhost:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
