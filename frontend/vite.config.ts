import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// يُبنى إلى app/static/app — تصله FastAPI عبر تركيب StaticFiles (app/main.py)
// مدخلان: index.html (واجهة الموظف) وportal.html (بوابة العميل، §٧-٦) —
// حزمتان مستقلتان تماماً، لا مشاركة شجرة React بينهما.
export default defineConfig({
  plugins: [react()],
  base: '/static/app/',
  build: {
    outDir: '../app/static/app',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL('index.html', import.meta.url)),
        portal: fileURLToPath(new URL('portal.html', import.meta.url)),
      },
    },
  },
  server: {
    proxy: {
      '/auth': 'http://127.0.0.1:8000',
      '/users': 'http://127.0.0.1:8000',
      '/operations': 'http://127.0.0.1:8000',
      '/reference': 'http://127.0.0.1:8000',
      '/clients': 'http://127.0.0.1:8000',
      '/journal': 'http://127.0.0.1:8000',
      '/dashboard': 'http://127.0.0.1:8000',
      '/position': 'http://127.0.0.1:8000',
      '/accounts': 'http://127.0.0.1:8000',
      '/lots': 'http://127.0.0.1:8000',
      '/portal': 'http://127.0.0.1:8000',
      '/search': 'http://127.0.0.1:8000',
      '/reports': 'http://127.0.0.1:8000',
      '/reconciliation': 'http://127.0.0.1:8000',
      '/settings': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
})
