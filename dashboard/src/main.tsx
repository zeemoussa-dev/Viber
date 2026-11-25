import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/tokens.css'
import './styles/shell.css'
import './styles/settings.css'
import './styles/layout.css'
import './styles/choices.css'
import './styles/components.css'
import './styles/charts.css'
// Last, so the glass and motion layer sits over every component's own rules.
import './styles/motion.css'
import './viber.css'
import { App } from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

