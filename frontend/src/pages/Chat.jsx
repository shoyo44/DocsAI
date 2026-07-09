import React, { useState, useEffect, useRef } from 'react';
import { Send, Bot, User, Sparkles, Loader2, Trash2, File, Loader, AlertCircle, Zap, Search, FileText, Scale, ChevronDown } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useApp } from '../context/AppContext';
import { useToast } from '../components/Toast';

import './Chat.css';

const cleanContent = (content) => {
  if (!content) return "";
  let text = content.trim();
  
  // Strip markdown JSON code fence wrappers
  text = text.replace(/^```(?:json)?\s*/i, "");
  text = text.replace(/\s*```$/, "");
  text = text.trim();
  
  if (text.startsWith("{") && text.endsWith("}")) {
    try {
      const parsed = JSON.parse(text);
      if (parsed && parsed.answer) {
        return parsed.answer;
      }
    } catch (e) {}
  }
  
  try {
    const match = text.match(/"answer"\s*:\s*"([^"]*)$/);
    if (match && match[1]) {
      return match[1].replace(/\\n/g, '\n').replace(/\\"/g, '"');
    }
    
    const matchComplete = text.match(/"answer"\s*:\s*"([^"]*)"/);
    if (matchComplete && matchComplete[1]) {
      return matchComplete[1].replace(/\\n/g, '\n').replace(/\\"/g, '"');
    }
  } catch (e) {}
  
  return content;
};

const Chat = () => {
  const { 
    vertical, setVertical, documents, activeJobs, tenantId, apiBase, wsBase,
    temperature, topK, scoreFloor 
  } = useApp();
  const toast = useToast();
  const [expandedEvidence, setExpandedEvidence] = useState({});
  const inputRef = useRef(null);
  
  const toggleEvidence = (idx) => {
    setExpandedEvidence(prev => ({
      ...prev,
      [idx]: !prev[idx]
    }));
  };

  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Hello! I am your Aura AI Agent. I can help you analyze documents, find compliance gaps, or summarize legal clauses. What should we look into today?' }
  ]);
  const [dbHistoryEnabled, setDbHistoryEnabled] = useState(false);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef(null);

  // Keyboard shortcut: Ctrl+K to focus input
  useEffect(() => {
    const handleKey = (e) => {
      if (e.ctrlKey && e.key === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, []);

  const scrollToBottom = () => {

    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Sync messages to localStorage (always runs as local fallback)
  useEffect(() => {
    if (messages.length > 0) {
      localStorage.setItem(`chat_history_${vertical}`, JSON.stringify(messages));
    }
  }, [messages, vertical]);

  // Load chat history from MongoDB with LocalStorage fallback
  useEffect(() => {
    let active = true;
    const loadHistory = async () => {
      try {
        const res = await fetch(`${apiBase}/history?tenant_id=${tenantId}&vertical=${vertical}`);
        if (!res.ok) throw new Error("History DB offline");
        const data = await res.json();
        if (active) {
          if (data.messages && data.messages.length > 0) {
            setMessages(data.messages);
          } else {
            setMessages([
              { role: 'assistant', content: `Hello! I am your Aura AI Agent for the ${vertical} workspace. I can help you analyze documents, find compliance gaps, or summarize legal clauses. What should we look into today?` }
            ]);
          }
          setDbHistoryEnabled(true);
        }
      } catch (err) {
        console.warn("MongoDB Atlas History DB offline, using LocalStorage:", err);
        if (active) {
          setDbHistoryEnabled(false);
          const saved = localStorage.getItem(`chat_history_${vertical}`);
          if (saved) {
            try {
              setMessages(JSON.parse(saved));
            } catch (e) {
              console.error("Failed to load local history:", e);
            }
          } else {
            setMessages([
              { role: 'assistant', content: `Hello! I am your Aura AI Agent for the ${vertical} workspace. I can help you analyze documents, find compliance gaps, or summarize legal clauses. What should we look into today?` }
            ]);
          }
        }
      }
    };

    loadHistory();
    return () => { active = false; };
  }, [apiBase, tenantId, vertical]);

  // Filter documents and jobs matching current vertical
  const activeDocs = vertical === 'auto'
    ? documents
    : documents.filter(doc => doc.vertical === vertical);

  const ongoingJobs = vertical === 'auto'
    ? activeJobs.filter(job => job.status === 'pending' || job.status === 'running')
    : activeJobs.filter(job => job.vertical === vertical && (job.status === 'pending' || job.status === 'running'));

  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;

    const queryText = input;
    const userMessage = { role: 'user', content: queryText };
    setMessages(prev => [...prev, userMessage]);

    setInput('');
    setIsTyping(true);

    // Create a placeholder for the assistant response
    setMessages(prev => [...prev, { role: 'assistant', content: '', isStreaming: true }]);

    try {
      const socket = new WebSocket(`${wsBase}/ws/query`);
      
      socket.onopen = () => {
        socket.send(JSON.stringify({
          question: input,
          tenant_id: tenantId,
          vertical: vertical,
          use_hyde: true,
          temperature: temperature,
          top_k: topK,
          score_floor: scoreFloor
        }));
      };


      socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === 'status') {
          setMessages(prev => {
            const newMessages = [...prev];
            const lastIdx = newMessages.length - 1;
            newMessages[lastIdx] = {
              ...newMessages[lastIdx],
              statusText: data.data
            };
            return newMessages;
          });
        } else if (data.type === 'chunks') {
          setMessages(prev => {
            const newMessages = [...prev];
            const lastIdx = newMessages.length - 1;
            newMessages[lastIdx] = {
              ...newMessages[lastIdx],
              evidence: data.data
            };
            return newMessages;
          });
        } else if (data.type === 'token') {
          setMessages(prev => {
            const newMessages = [...prev];
            const lastIdx = newMessages.length - 1;
            newMessages[lastIdx] = {
              ...newMessages[lastIdx],
              content: newMessages[lastIdx].content + data.data
            };
            return newMessages;
          });


        } else if (data.type === 'done') {
          setMessages(prev => {
            const newMessages = [...prev];
            const lastIdx = newMessages.length - 1;
            newMessages[lastIdx] = {
              ...newMessages[lastIdx],
              ...data.data,
              isStreaming: false
            };
            return newMessages;
          });
          socket.close();
          setIsTyping(false);

          // Sync user and assistant responses to MongoDB with the resolved vertical
          if (dbHistoryEnabled) {
            try {
              const resolvedVertical = data.data.vertical || vertical;
              const assistantContent = data.data.answer || data.data.content || '';
              
              // 1. Sync User Message
              fetch(`${apiBase}/history/message`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  tenant_id: tenantId,
                  vertical: resolvedVertical,
                  role: 'user',
                  content: queryText
                })
              }).catch(err => console.warn("Failed to sync user message:", err));

              // 2. Sync Assistant Message
              fetch(`${apiBase}/history/message`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  tenant_id: tenantId,
                  vertical: resolvedVertical,
                  role: 'assistant',
                  content: assistantContent,
                  evidence: data.data.evidence || [],
                  citations: data.data.citations || [],
                  paper_title: data.data.paper_title,
                  authors: data.data.authors || [],
                  abstract_summary: data.data.abstract_summary
                })
              }).catch(err => console.warn("Failed to sync assistant message:", err));
              
            } catch (err) {
              console.warn("Failed to sync conversation messages:", err);
            }
          }

        } else if (data.type === 'error') {
          setMessages(prev => {
            const newMessages = [...prev];
            newMessages[newMessages.length - 1].content = "Error: " + data.data;
            newMessages[newMessages.length - 1].isStreaming = false;
            return newMessages;
          });
          socket.close();
          setIsTyping(false);
        }
      };

      socket.onerror = (err) => {
        console.error("WS Error:", err);
        toast.error("Connection Error", "Failed to connect to RAG server. Make sure backend is running.");
        setIsTyping(false);
      };

    } catch (error) {
      console.error("Chat Error:", error);
      toast.error("Execution Error", "An unexpected error occurred during pipeline startup.");
      setIsTyping(false);
    }
  };

  return (
    <div className="chat-page-layout animate-fade-in">
      <div className="chat-container">
        <div className="chat-header">
          <div className="header-info">
            <h1>Agentic Workspace</h1>
            <p className="subtitle">Context-aware multi-vertical analysis</p>
          </div>
          <div className="chat-actions">
            <button className="clear-chat-btn" onClick={async () => {
              if (dbHistoryEnabled) {
                try {
                  const res = await fetch(`${apiBase}/history?tenant_id=${tenantId}&vertical=${vertical}`, {
                    method: 'DELETE'
                  });
                  if (res.ok) {
                    toast.success("Chat History Cleared", "MongoDB session logs have been purged.");
                  } else {
                    toast.warning("Local Reset Only", "Failed to purge database chat logs, but cleared locally.");
                  }
                } catch (err) {
                  console.warn("Failed to clear database history:", err);
                  toast.warning("Local Reset Only", "Failed to purge database chat logs, but cleared locally.");
                }
              } else {
                toast.info("Cleared Local Session", "Local storage message log has been reset.");
              }
              localStorage.removeItem(`chat_history_${vertical}`);
              setMessages([{ role: 'assistant', content: `Hello! I am your Aura AI Agent for the ${vertical} workspace. I can help you analyze documents, find compliance gaps, or summarize legal clauses. What should we look into today?` }]);
            }}>
              <Trash2 size={14} /> Clear Chat
            </button>
            <div className="vertical-selector-chat">
              <Sparkles size={14} />
              <select value={vertical} onChange={(e) => setVertical(e.target.value)}>
                <option value="auto">🧠 Auto-Route (AI)</option>
                <option value="law">Law</option>
                <option value="university">University</option>
                <option value="startup">Startup</option>
                <option value="compliance">Compliance</option>
                <option value="hr">HR</option>
              </select>
            </div>
          </div>


        </div>

        <div className="chat-messages glass-panel">
          {/* Welcome Hero — shown only when single welcome message exists */}
          {messages.length === 1 && messages[0].role === 'assistant' && !isTyping && (
            <div className="welcome-hero">
              <div className="welcome-logo-ring">
                <Zap size={32} />
              </div>
              <h2 className="welcome-title">What can I help you discover?</h2>
              <p className="welcome-subtitle">Ask anything about your uploaded documents — I'll search, analyze, and cite sources.</p>
              <div className="quick-prompts">
                {[
                  { icon: Search, text: "Summarize the key findings of my research paper" },
                  { icon: Scale, text: "What are the liability clauses in the contract?" },
                  { icon: FileText, text: "List all compliance requirements mentioned" },
                ].map((prompt, i) => (
                  <button
                    key={i}
                    className="quick-prompt-pill hover-lift"
                    onClick={() => {
                      setInput(prompt.text);
                      setTimeout(() => {
                        const form = document.querySelector('.chat-input-area');
                        if (form) form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                      }, 50);
                    }}
                  >
                    <prompt.icon size={14} />
                    <span>{prompt.text}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, idx) => (
            <div key={idx} className={`message-wrapper ${msg.role}`}>
              <div className="message-icon">
                {msg.role === 'assistant' ? <Bot size={20} /> : <User size={20} />}
              </div>
              <div className="message-content">
                {/* Structured Metadata Card (for University/Academic) */}
                {msg.role === 'assistant' && (msg.paper_title || msg.authors?.length > 0) && (
                  <div className="metadata-card animate-slide-up">
                    <div className="metadata-label">DOCUMENT METADATA</div>
                    <h2 className="paper-title">{msg.paper_title || "Unknown Title"}</h2>
                    <div className="authors-list">
                      {msg.authors?.map((a, i) => <span key={i} className="author-tag">{a}</span>)}
                    </div>
                    {msg.abstract_summary && <p className="abstract-text">{msg.abstract_summary}</p>}
                  </div>
                )}

                {msg.role === 'assistant' && msg.evidence?.length > 0 && (
                  <div className="evidence-panel">
                    <button 
                      className="evidence-toggle"
                      onClick={() => toggleEvidence(idx)}
                    >
                      <Sparkles size={14} />
                      <span>Found {msg.evidence.length} evidence chunks</span>
                      <ChevronDown size={14} className={`arrow ${expandedEvidence[idx] ? 'open' : ''}`} />
                    </button>
                    
                    {expandedEvidence[idx] && (
                      <div className="evidence-list animate-fade-in">
                        {msg.evidence.map((ev, i) => (
                          <div key={i} className="evidence-card">
                            <div className="evidence-header">
                              <span className="source-tag">Source: {ev.doc_name || ev.metadata?.filename || 'Unknown Document'}</span>
                              <span className="score-tag">Score: {ev.score ? ev.score.toFixed(3) : 'N/A'}</span>
                            </div>
                            <p className="evidence-text">{ev.text || ev.content}</p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className="answer-text markdown-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {cleanContent(msg.content)}
                  </ReactMarkdown>
                </div>

                {msg.citations?.length > 0 && (
                  <div className="citations">
                    {msg.citations.map((c, i) => (
                      <span key={i} className="citation-tag">
                        Clause {c.clause || c.article || 'Ref'}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {isTyping && (
            <div className="message-wrapper assistant">
              <div className="message-icon"><Bot size={20} /></div>
              <div className="message-content typing animate-pulse">
                <Loader2 className="spin text-accent" size={18} />
                <span>{messages[messages.length - 1]?.statusText || "Thinking..."}</span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <form className="chat-input-area" onSubmit={handleSend}>
          <input 
            ref={inputRef}
            type="text" 
            placeholder="Ask about your documents (e.g., 'What is the liability cap in the vendor agreement?')"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={isTyping}
          />
          <button type="submit" className="send-button" disabled={isTyping || !input.trim()}>
            <Send size={20} />
          </button>
        </form>
      </div>

      <div className="chat-reference-panel glass-panel">
        <h3 className="reference-title">Reference Context</h3>
        <p className="reference-subtitle">Loaded knowledge sources for the <strong className="vertical-name-highlight">{vertical}</strong> workspace.</p>
        
        {ongoingJobs.length > 0 && (
          <div className="ref-jobs-list">
            {ongoingJobs.map(job => (
              <div key={job.id} className="ref-job-item">
                <Loader className="spin text-accent" size={14} />
                <div className="ref-job-details">
                  <span className="ref-job-name" title={job.name}>{job.name}</span>
                  <span className="ref-job-desc">Ingesting & indexing...</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {activeDocs.length === 0 && ongoingJobs.length === 0 ? (
          <div className="ref-empty-state">
            <AlertCircle size={24} className="text-tertiary" />
            <p className="empty-title">Workspace is empty</p>
            <p className="empty-desc">
              {vertical === 'auto' 
                ? "There are no documents uploaded in any workspace vertical yet."
                : `There are no documents uploaded in the ${vertical} vertical yet.`
              }
            </p>
            <p className="empty-action-hint">
              Go to the <strong>Document Vault</strong> to upload and index documents{vertical !== 'auto' && ` for the ${vertical} vertical`}.
            </p>
          </div>
        ) : (
          <div className="ref-docs-list">
            {activeDocs.map(doc => (
              <div key={doc.id} className="ref-doc-card">
                <File size={16} className="text-accent flex-shrink-0" />
                <div className="ref-doc-details">
                  <span className="ref-doc-name" title={doc.name}>{doc.name}</span>
                  <span className="ref-doc-meta">
                    <span className="badge-vertical-ref" style={{ 
                      fontSize: '0.62rem', 
                      fontWeight: '800', 
                      color: 'var(--accent-primary)',
                      marginRight: '0.35rem',
                      textTransform: 'uppercase'
                    }}>{doc.vertical}</span> • {doc.chunks_count} chunks
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default Chat;
