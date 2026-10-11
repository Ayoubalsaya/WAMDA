import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './design/base.css'
import { PortalApp } from './portal/PortalApp.tsx'
import { loadEnvironment } from './api/environment'
import { EnvBadge } from './components/EnvBadge'

// نفس منطق main.tsx؛ الشارة لا تُعرَض للعميل في الإنتاج (hideInProduction).
void loadEnvironment().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <EnvBadge hideInProduction />
      <PortalApp />
    </StrictMode>,
  )
})
