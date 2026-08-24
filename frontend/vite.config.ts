import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// يُبنى إلى app/static/app — تصله FastAPI عبر تركيب StaticFiles (app/main.py)
export default defineConfig({
  plugins: [react()],
  base: '/static/app/',
  build: {
    outDir: '../app/static/app',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/auth': 'http://127.0.0.1:8000',
      '/users': 'http://127.0.0.1:8000',
      '/operations': 'http://127.0.0.1:8000',
      '/reference': 'http://127.0.0.1:8000',
      '/clients': 'http://127.0.0.1:8000',
      '/journal': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
})
