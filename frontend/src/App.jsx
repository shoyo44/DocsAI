import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import Layout from './components/Layout';
import Vault from './pages/Vault';
import Chat from './pages/Chat';
import Analytics from './pages/Analytics';
import Settings from './pages/Settings';
import History from './pages/History';
import Starter from './pages/Starter';
import Login from './pages/Login';
import { AppContextProvider, useApp } from './context/AppContext';
import { ToastProvider } from './components/Toast';
import './components/Toast.css';

// Authentication Guard Component
const AuthGuard = ({ children }) => {
  const { user } = useApp();
  const location = useLocation();

  if (!user) {
    // Redirect to login page while preserving redirection path history
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return children;
};

function App() {
  return (
    <AppContextProvider>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            {/* Public starter landing page */}
            <Route path="/" element={<Starter />} />
            
            {/* Gmail single sign-on page */}
            <Route path="/login" element={<Login />} />

            {/* Authenticated workspace views */}
            <Route path="/" element={<AuthGuard><Layout /></AuthGuard>}>
              <Route path="chat" element={<Chat />} />
              <Route path="vault" element={<Vault />} />
              <Route path="analytics" element={<Analytics />} />
              <Route path="history" element={<History />} />
              <Route path="settings" element={<Settings />} />
            </Route>

            {/* Catch-all fallback */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </AppContextProvider>
  );
}

export default App;
