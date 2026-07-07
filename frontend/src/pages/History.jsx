import React, { useState, useEffect, useCallback } from 'react';
import { Clock, Search, MessageSquare, Database, Trash2, Cpu, ChevronRight, AlertCircle, Calendar, Zap, RefreshCw, Filter } from 'lucide-react';
import { useApp } from '../context/AppContext';
import './History.css';

const History = () => {
  const { tenantId, vertical: appVertical, apiBase } = useApp();
  const [activeTab, setActiveTab] = useState('queries'); // 'queries' or 'chats'
  const [selectedVertical, setSelectedVertical] = useState(appVertical || 'all');
  const [queries, setQueries] = useState([]);
  const [chats, setChats] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [clearing, setClearing] = useState(false);

  // Fetch recent RAG queries logged in MongoDB
  const fetchQueries = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/analytics/recent?tenant_id=${tenantId}&limit=50`);
      if (!res.ok) throw new Error("Could not fetch query history.");
      const data = await res.json();
      setQueries(data.queries || []);
    } catch (err) {
      console.error(err);
      setError("Failed to retrieve query log history from MongoDB.");
    }
  }, [apiBase, tenantId]);

  // Fetch chat message history logged in MongoDB
  const fetchChats = useCallback(async () => {
    // If selecting 'all', we will loop through each vertical to collect them, or show current workspace
    const verticalsToFetch = selectedVertical === 'all' 
      ? ['university', 'law', 'startup', 'compliance', 'hr'] 
      : [selectedVertical];
    
    try {
      let allMessages = [];
      for (const vert of verticalsToFetch) {
        const res = await fetch(`${apiBase}/history?tenant_id=${tenantId}&vertical=${vert}`);
        if (res.ok) {
          const data = await res.json();
          if (data.messages && data.messages.length > 0) {
            // Annotate messages with their vertical source
            const annotated = data.messages.map(m => ({ ...m, vertical: vert }));
            allMessages = [...allMessages, ...annotated];
          }
        }
      }
      // Sort messages by creation or grouping if timestamp exists
      setChats(allMessages);
    } catch (err) {
      console.error(err);
      setError("Failed to retrieve chat message history from MongoDB.");
    }
  }, [apiBase, tenantId, selectedVertical]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    if (activeTab === 'queries') {
      await fetchQueries();
    } else {
      await fetchChats();
    }
    setLoading(false);
  }, [activeTab, fetchQueries, fetchChats]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleClearChats = async () => {
    const targetVert = selectedVertical === 'all' ? 'university' : selectedVertical;
    const confirmMsg = selectedVertical === 'all' 
      ? "Clear chat history for all verticals? (This will clear the current vertical's history)"
      : `Clear chat history for the ${selectedVertical} vertical?`;

    if (!window.confirm(confirmMsg)) return;

    setClearing(true);
    try {
      const verticalsToClear = selectedVertical === 'all' 
        ? ['university', 'law', 'startup', 'compliance', 'hr'] 
        : [selectedVertical];

      for (const vert of verticalsToClear) {
        await fetch(`${apiBase}/history?tenant_id=${tenantId}&vertical=${vert}`, {
          method: 'DELETE'
        });
      }
      setChats([]);
      alert("Chat history successfully cleared.");
    } catch (err) {
      alert("Failed to clear chat history: " + err.message);
    } finally {
      setClearing(false);
      loadData();
    }
  };

  const getVerticalLabel = (v) => {
    const labels = {
      university: 'Academic',
      law: 'Legal',
      startup: 'Startup & VC',
      compliance: 'Compliance',
      hr: 'HR Policy',
    };
    return labels[v] || v;
  };

  const getVerticalColor = (v) => {
    const colors = {
      university: '#da77f2',
      law: '#f06595',
      startup: '#ffd43b',
      compliance: '#63e6be',
      hr: '#4dabf7',
    };
    return colors[v] || '#8c8c8c';
  };

  const filteredQueries = selectedVertical === 'all'
    ? queries
    : queries.filter(q => q.vertical === selectedVertical);

  return (
    <div className="history-container animate-fade-in">
      <div className="history-header">
        <div className="header-title-row">
          <div>
            <h1>MongoDB Shared History</h1>
            <p className="subtitle">Audit recent queries, latency metrics, and conversation records synced with Atlas.</p>
          </div>
          <button className="refresh-btn hover-lift" onClick={loadData} disabled={loading}>
            <RefreshCw size={15} className={loading ? "spin" : ""} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      <div className="history-tabs-toolbar">
        <div className="tabs">
          <button 
            className={`tab-btn ${activeTab === 'queries' ? 'active' : ''}`}
            onClick={() => setActiveTab('queries')}
          >
            <Search size={16} />
            <span>RAG Query Logs</span>
          </button>
          <button 
            className={`tab-btn ${activeTab === 'chats' ? 'active' : ''}`}
            onClick={() => setActiveTab('chats')}
          >
            <MessageSquare size={16} />
            <span>Chat Messages</span>
          </button>
        </div>

        <div className="filters">
          <div className="filter-wrapper">
            <Filter size={14} className="filter-icon" />
            <select 
              value={selectedVertical} 
              onChange={(e) => setSelectedVertical(e.target.value)}
              className="vertical-select"
            >
              <option value="all">All Verticals</option>
              <option value="university">Academic Research</option>
              <option value="law">Legal Contracts</option>
              <option value="startup">Startup & VC</option>
              <option value="compliance">Compliance</option>
              <option value="hr">HR Policies</option>
            </select>
          </div>

          {activeTab === 'chats' && chats.length > 0 && (
            <button 
              className="clear-btn hover-lift" 
              onClick={handleClearChats} 
              disabled={clearing}
            >
              <Trash2 size={14} />
              <span>Clear History</span>
            </button>
          )}
        </div>
      </div>

      {error ? (
        <div className="history-error-card glass-panel">
          <AlertCircle size={32} className="text-error" />
          <p>{error}</p>
          <button className="retry-btn" onClick={loadData}>Retry Connection</button>
        </div>
      ) : loading ? (
        <div className="history-loader">
          <Clock size={40} className="spin text-accent" />
          <p>Retrieving MongoDB audit logs...</p>
        </div>
      ) : activeTab === 'queries' ? (
        <div className="history-content-grid">
          {filteredQueries.length === 0 ? (
            <div className="empty-history-state glass-panel">
              <Database size={48} style={{ opacity: 0.3 }} />
              <h3>No query logs found</h3>
              <p>Ask questions in the Agent Chat to generate search logs in MongoDB.</p>
            </div>
          ) : (
            <div className="queries-list">
              {filteredQueries.map((q, idx) => (
                <div key={idx} className="query-log-card glass-panel hover-lift">
                  <div className="card-top-row">
                    <span 
                      className="vertical-badge" 
                      style={{ 
                        color: getVerticalColor(q.vertical), 
                        borderColor: getVerticalColor(q.vertical) 
                      }}
                    >
                      {getVerticalLabel(q.vertical)}
                    </span>

                    <div className="stats-row">
                      {q.latency_ms > 0 && (
                        <span className="stat-tag latency">
                          <Zap size={10} />
                          {q.latency_ms.toFixed(0)} ms
                        </span>
                      )}
                      {q.confidence && (
                        <span className={`stat-tag confidence ${q.confidence.toLowerCase()}`}>
                          {q.confidence}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="query-question">
                    <span className="q-indicator">Q</span>
                    <h4>{q.query}</h4>
                  </div>

                  <div className="query-answer">
                    <span className="a-indicator">A</span>
                    <p>{q.answer || "No answer returned."}</p>
                  </div>

                  {q.created_at && (
                    <div className="card-footer-info">
                      <Calendar size={11} />
                      <span>{new Date(q.created_at * 1000).toLocaleString()}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="history-content-grid">
          {chats.length === 0 ? (
            <div className="empty-history-state glass-panel">
              <MessageSquare size={48} style={{ opacity: 0.3 }} />
              <h3>No chat messages synced</h3>
              <p>Ask queries using the chat screen to log assistant conversations.</p>
            </div>
          ) : (
            <div className="chats-thread-view glass-panel">
              <div className="thread-messages">
                {chats.map((msg, idx) => (
                  <div key={idx} className={`thread-msg-item ${msg.role}`}>
                    <div className="msg-avatar-wrapper">
                      <span className="msg-avatar">
                        {msg.role === 'user' ? 'U' : 'AI'}
                      </span>
                    </div>
                    <div className="msg-bubble-content">
                      <div className="msg-meta-header">
                        <span className="role-name">
                          {msg.role === 'user' ? 'User' : 'Assistant'}
                        </span>
                        <span 
                          className="msg-vertical-tag" 
                          style={{ color: getVerticalColor(msg.vertical) }}
                        >
                          · {getVerticalLabel(msg.vertical)}
                        </span>
                      </div>
                      <p className="msg-text">{msg.content}</p>
                      {msg.paper_title && (
                        <div className="citation-attachment">
                          <strong>Source:</strong> {msg.paper_title}
                          {msg.authors && msg.authors.length > 0 && ` by ${msg.authors.join(', ')}`}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default History;
