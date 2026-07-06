import React from 'react';
import './Dashboard.css';

const Dashboard = () => {
  return (
    <div className="dashboard-container animate-fade-in">
      <header className="dashboard-header">
        <div>
          <h1>Welcome back, Dr. Developer</h1>
          <p className="subtitle">Here's what's happening with your AI infrastructure today.</p>
        </div>
        <button className="primary-button hover-lift">
          Upload Document
        </button>
      </header>

      <div className="stats-grid">
        <div className="stat-card glass-panel hover-lift">
          <span className="stat-label">Total Documents</span>
          <h3 className="stat-value">1,248</h3>
          <span className="stat-trend positive">↑ 12% from last week</span>
        </div>
        <div className="stat-card glass-panel hover-lift">
          <span className="stat-label">Graph Entities</span>
          <h3 className="stat-value">45,912</h3>
          <span className="stat-trend positive">↑ 8% from last week</span>
        </div>
        <div className="stat-card glass-panel hover-lift">
          <span className="stat-label">Agent Queries</span>
          <h3 className="stat-value">342</h3>
          <span className="stat-trend neutral">Stable</span>
        </div>
        <div className="stat-card glass-panel hover-lift">
          <span className="stat-label">System Health</span>
          <h3 className="stat-value">99.9%</h3>
          <span className="stat-trend positive">All systems operational</span>
        </div>
      </div>

      <div className="dashboard-bento">
        <div className="bento-card large glass-panel">
          <h3>Recent Agent Activity</h3>
          <div className="placeholder-chart">
            <p className="placeholder-text">Activity Timeline Visualization</p>
          </div>
        </div>
        
        <div className="bento-card glass-panel">
          <h3>Latest Insights</h3>
          <ul className="insight-list">
            <li>
              <div className="insight-dot critical"></div>
              <div>
                <strong>High Risk Clause Detected</strong>
                <p>Uncapped liability found in "Vendor_Agreement_Q3.pdf"</p>
              </div>
            </li>
            <li>
              <div className="insight-dot warning"></div>
              <div>
                <strong>Compliance Gap</strong>
                <p>GDPR update affects 3 internal policies.</p>
              </div>
            </li>
            <li>
              <div className="insight-dot success"></div>
              <div>
                <strong>Batch Ingestion Complete</strong>
                <p>Successfully processed 42 employee handbooks.</p>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
