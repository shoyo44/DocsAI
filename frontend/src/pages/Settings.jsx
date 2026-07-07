import React, { useState, useEffect } from 'react';
import { Settings as SettingsIcon, Shield, Database, Sparkles, RefreshCw, Trash2, Cpu, CheckCircle2, XCircle, AlertCircle } from 'lucide-react';
import { useApp } from '../context/AppContext';
import './Settings.css';

const Settings = () => {
  const { tenantId, vertical, setVertical, apiBase } = useApp();
  const [theme, setTheme] = useState('dark');
  const [temperature, setTemperature] = useState(0.05);
  const [topK, setTopK] = useState(10);
  const [scoreFloor, setScoreFloor] = useState(0.40);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);
  
  // Health connection statuses
  const [health, setHealth] = useState({
    graph_store: 'loading',
    redis: 'loading',
    mongodb: 'loading'
  });

  const checkHealth = async () => {
    try {
      // Fetch /health from backend root (since apiBase is usually /api/v1, let's remove /api/v1 or fetch relative to backend root)
      const healthUrl = apiBase.replace('/api/v1', '') + '/health';
      const res = await fetch(healthUrl);
      if (res.ok) {
        const data = await res.json();
        setHealth({
          graph_store: data.database?.graph_store || 'failed',
          redis: data.database?.redis || 'disabled',
          mongodb: data.database?.mongodb || 'disabled'
        });
      } else {
        throw new Error();
      }
    } catch (e) {
      setHealth({
        graph_store: 'failed',
        redis: 'failed',
        mongodb: 'failed'
      });
    }
  };

  useEffect(() => {
    checkHealth();
  }, [apiBase]);

  const handleClearCache = async () => {
    if (!window.confirm("Are you sure you want to clear all graph store data? This deletes all nodes, chunks, and relationships.")) return;
    setLoading(true);
    try {
      const response = await fetch(`${apiBase}/documents?tenant_id=${tenantId}`, {
        method: 'DELETE'
      });
      if (response.ok) {
        setMessage({ type: 'success', text: 'Graph Store cleared successfully.' });
      } else {
        setMessage({ type: 'error', text: 'Failed to clear Graph Store.' });
      }
    } catch (err) {
      setMessage({ type: 'error', text: `Error: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="settings-container animate-fade-in">
      <div className="settings-header">
        <h1>System Settings</h1>
        <p className="subtitle">Tune pipeline thresholds, manage databases, and review connection properties.</p>
      </div>

      <div className="settings-grid">
        <div className="settings-card glass-panel">
          <div className="card-header">
            <Cpu size={20} className="icon-accent" />
            <h3>RAG Pipeline Parameters</h3>
          </div>
          <div className="card-body">
            <div className="setting-row">
              <label>Current Tenant ID</label>
              <input type="text" value={tenantId} readOnly className="read-only-input" />
            </div>

            <div className="setting-row">
              <label>Active Workspace Vertical</label>
              <select value={vertical} onChange={(e) => setVertical(e.target.value)}>
                <option value="university">University Papers</option>
                <option value="law">Legal Contracts</option>
                <option value="startup">Startup & VC</option>
                <option value="compliance">Compliance Regulations</option>
                <option value="hr">HR Policies</option>
              </select>
            </div>

            <div className="setting-row">
              <label>LLM Temperature ({temperature})</label>
              <input 
                type="range" 
                min="0" 
                max="1" 
                step="0.05" 
                value={temperature} 
                onChange={(e) => setTemperature(parseFloat(e.target.value))} 
              />
              <span className="hint-text">Lower is more deterministic; higher is more creative.</span>
            </div>

            <div className="setting-row">
              <label>Retriever Chunks Limit (Top K: {topK})</label>
              <input 
                type="range" 
                min="1" 
                max="30" 
                value={topK} 
                onChange={(e) => setTopK(parseInt(e.target.value))} 
              />
            </div>

            <div className="setting-row">
              <label>Relevance Score Floor ({(scoreFloor * 100).toFixed(0)}%)</label>
              <input 
                type="range" 
                min="0.10" 
                max="0.90" 
                step="0.05" 
                value={scoreFloor} 
                onChange={(e) => setScoreFloor(parseFloat(e.target.value))} 
              />
              <span className="hint-text">Chunks below this vector score will be gated.</span>
            </div>
          </div>
        </div>

        <div className="settings-card glass-panel">
          <div className="card-header">
            <Database size={20} className="icon-accent" />
            <h3>Database & Connectors</h3>
          </div>
          <div className="card-body">
            <div className="connector-status">
              <div className="status-item">
                {health.graph_store === 'connected' ? (
                  <CheckCircle2 size={16} className="text-success" />
                ) : health.graph_store === 'loading' ? (
                  <RefreshCw size={16} className="spin text-accent" />
                ) : (
                  <XCircle size={16} className="text-error" />
                )}
                <div>
                  <strong>Graph Database</strong>
                  <span>{health.graph_store === 'connected' ? 'In-Process Store Connected (NetworkX + NumPy)' : health.graph_store === 'loading' ? 'Checking status...' : 'Disconnected / Failure'}</span>
                </div>
              </div>

              <div className="status-item">
                {health.mongodb === 'connected' ? (
                  <CheckCircle2 size={16} className="text-success" />
                ) : health.mongodb === 'connected_fallback' ? (
                  <CheckCircle2 size={16} style={{ color: '#ffd43b' }} />
                ) : health.mongodb === 'loading' ? (
                  <RefreshCw size={16} className="spin text-accent" />
                ) : health.mongodb === 'disabled' ? (
                  <Shield size={16} style={{ color: 'var(--text-tertiary)' }} />
                ) : (
                  <XCircle size={16} className="text-error" />
                )}
                <div>
                  <strong>MongoDB History DB</strong>
                  <span>
                    {health.mongodb === 'connected' && 'Connected to Atlas'}
                    {health.mongodb === 'connected_fallback' && 'Connected (Local JSON Fallback)'}
                    {health.mongodb === 'loading' && 'Checking status...'}
                    {health.mongodb === 'disabled' && 'Disabled (Not configured)'}
                    {health.mongodb === 'failed' && 'Failed to connect (Check credentials)'}
                  </span>
                </div>
              </div>

              <div className="status-item">
                <CheckCircle2 size={16} className="text-success" />
                <div>
                  <strong>Embeddings API</strong>
                  <span>Nomic Atlas API (nomic-embed-text-v1.5)</span>
                </div>
              </div>

              <div className="status-item">
                <CheckCircle2 size={16} className="text-success" />
                <div>
                  <strong>LLM Engine</strong>
                  <span>Cloudflare Workers AI (LLaMA 3.3 70B)</span>
                </div>
              </div>
            </div>

            <hr className="divider" />

            <div className="danger-zone">
              <h4>Danger Zone</h4>
              <p>Destructive actions that cannot be undone.</p>
              <button className="danger-button hover-lift" onClick={handleClearCache} disabled={loading}>
                <Trash2 size={16} /> {loading ? "Clearing..." : "Purge Graph Database"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {message && (
        <div className={`alert ${message.type} animate-fade-in`}>
          <span>{message.text}</span>
        </div>
      )}
    </div>
  );
};

export default Settings;
