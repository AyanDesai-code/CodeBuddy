import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import Design2 from './Design2'
import './style.css'

const rootElement = document.getElementById('design2-root')

if (rootElement) {
  createRoot(rootElement).render(
    <StrictMode>
      <Design2
        startUrl={rootElement.dataset.startUrl ?? '/accounts/signup/'}
        loginUrl={rootElement.dataset.loginUrl ?? '/accounts/login/'}
      />
    </StrictMode>,
  )
}