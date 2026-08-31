import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './design/base.css'
import { PortalApp } from './portal/PortalApp.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PortalApp />
  </StrictMode>,
)
