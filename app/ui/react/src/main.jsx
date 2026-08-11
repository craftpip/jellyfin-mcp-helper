import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import { AppStoreProvider } from './store/AppStore.jsx'
import './styles/theme.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AppStoreProvider>
      <App />
    </AppStoreProvider>
  </React.StrictMode>
)
