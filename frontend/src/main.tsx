import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './design/base.css'
import App from './App.tsx'
import { loadEnvironment } from './api/environment'
import { EnvBadge } from './components/EnvBadge'

// البيئة (وكوكي CSRF الخاص بها) تُحمَّل قبل الرسم: أول طلب كتابة يحتاج اسم الكوكي الصحيح، والعلامة تظهر حتى على شاشة الدخول.
void loadEnvironment().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <EnvBadge />
      <App />
    </StrictMode>,
  )
})
