import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Vault from './pages/Vault';
import Chat from './pages/Chat';
import Analytics from './pages/Analytics';
import Settings from './pages/Settings';
import History from './pages/History';
import { AppContextProvider } from './context/AppContext';

function App() {
  return (
    <AppContextProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Navigate to="/chat" replace />} />
            <Route path="vault" element={<Vault />} />
            <Route path="chat" element={<Chat />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="history" element={<History />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppContextProvider>
  );
}

export default App;
