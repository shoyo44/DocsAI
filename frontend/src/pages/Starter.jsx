import React from 'react';
import { useNavigate } from 'react-router-dom';
import { MessageSquare, Files, Activity, Clock, ShieldCheck, ArrowRight, Zap, Target, BookOpen, Layers } from 'lucide-react';
import { useApp } from '../context/AppContext';
import logoUrl from '../assets/logo.png';
import './Starter.css';

const Starter = () => {
  const { user, documents } = useApp();
  const navigate = useNavigate();

  const handleLaunch = () => {
    if (user) {
      navigate('/chat');
    } else {
      navigate('/login');
    }
  };

  const features = [
    {
      icon: MessageSquare,
      title: "Context-Aware Agentic Chat",
      desc: "Converse with specialized document agents using hybrid semantic retrieval and live routing."
    },
    {
      icon: Files,
      title: "Document Ingestion Vault",
      desc: "Upload contracts, research papers, or manuals. Automated AI classification routes documents into vector store collections."
    },
    {
      icon: Activity,
      title: "Graph Intelligence & Inspector",
      desc: "Explore entity-relationship mappings, zoom to target nodes, and trace entity connection graphs."
    },
    {
      icon: Clock,
      title: "MongoDB Auditing Logs",
      desc: "Analyze previous queries, trace pipeline latency metrics, and retrieve conversation session logs."
    }
  ];

  return (
    <div className="starter-page-container animate-fade-in">
      <div className="starter-mesh-grid"></div>

      <header className="starter-nav-header">
        <div className="starter-nav-logo">
          <img src={logoUrl} alt="DocsAI Logo" className="starter-logo-img" />
          <h2>DocsAI</h2>
        </div>
        <button className="starter-nav-cta hover-lift" onClick={handleLaunch}>
          {user ? "Enter Workspace" : "Sign In"}
        </button>
      </header>

      <main className="starter-main-hero">
        <div className="starter-hero-content">
          <div className="starter-pill-badge">
            <Zap size={13} />
            <span>Multi-Vertical Agentic RAG Platform</span>
          </div>
          <h1>
            Your Knowledge Base, <br />
            <span>Transformed into Agents</span>
          </h1>
          <p className="starter-hero-subtitle">
            Upload text, contracts, or compliance regulations. DocsAI automatically classifies, indexes, and enables context-aware interactive reasoning with structured citations.
          </p>

          <div className="starter-cta-group">
            <button className="starter-hero-btn-primary hover-lift" onClick={handleLaunch}>
              <span>Launch Workspace</span>
              <ArrowRight size={16} />
            </button>
          </div>

          <div className="starter-hero-stats">
            <div className="stat-card">
              <h3>{documents.length || 5}+</h3>
              <span>Active Documents</span>
            </div>
            <div className="stat-card">
              <h3>5+</h3>
              <span>Specialized Verticals</span>
            </div>
            <div className="stat-card">
              <h3>&lt; 2.5s</h3>
              <span>Average Retrieval Latency</span>
            </div>
          </div>
        </div>

        <div className="starter-feature-section">
          <h2>Platform Capabilities</h2>
          <div className="features-grid">
            {features.map((f, i) => (
              <div key={i} className="feature-card glass-panel hover-lift">
                <div className="feature-card-icon">
                  <f.icon size={22} />
                </div>
                <h3>{f.title}</h3>
                <p>{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </main>

      <footer className="starter-page-footer">
        <p>&copy; {new Date().getFullYear()} DocsAI Inc. Aura AI Agent Workspace.</p>
      </footer>
    </div>
  );
};

export default Starter;
