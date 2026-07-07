import React, { useState, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import { MessageSquare, Files, Settings, Activity, Loader, CheckCircle2, XCircle, Clock, Sun, Moon } from 'lucide-react';
import { useApp } from '../context/AppContext';
import './Sidebar.css';

const Sidebar = () => {
  const { activeJobs } = useApp();
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'dark');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark');
  };

  const navItems = [
    { name: 'Agent Chat', path: '/chat', icon: MessageSquare },
    { name: 'Document Vault', path: '/vault', icon: Files },
    { name: 'Analytics', path: '/analytics', icon: Activity },
    { name: 'History', path: '/history', icon: Clock },
    { name: 'Settings', path: '/settings', icon: Settings },
  ];

  return (
    <aside className="sidebar glass-panel">
      <div className="sidebar-header">
        <div className="logo-icon"></div>
        <h2>Aura AI</h2>
      </div>
      
      <nav className="sidebar-nav">
        {navItems.map((item) => (
          <NavLink 
            to={item.path} 
            key={item.name}
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
          >
            <item.icon size={20} />
            <span>{item.name}</span>
          </NavLink>
        ))}
      </nav>

      {activeJobs && activeJobs.length > 0 && (
        <div className="sidebar-jobs">
          <div className="jobs-header">BACKGROUND TASKS</div>
          <div className="jobs-list">
            {activeJobs.map(job => (
              <div key={job.id} className={`job-status-item ${job.status}`}>
                <div className="job-status-icon">
                  {job.status === 'pending' && <Clock className="pulse" size={14} />}
                  {job.status === 'running' && <Loader className="spin text-accent" size={14} />}
                  {job.status === 'completed' && <CheckCircle2 className="text-success" size={14} />}
                  {job.status === 'failed' && <XCircle className="text-error" size={14} />}
                </div>
                <div className="job-status-details">
                  <span className="job-status-name" title={job.name}>{job.name}</span>
                  <span className="job-status-desc">
                    {job.status === 'pending' && 'Pending queue...'}
                    {job.status === 'running' && 'Ingesting & indexing...'}
                    {job.status === 'completed' && `Complete! +${job.chunksCreated} chunks`}
                    {job.status === 'failed' && 'Ingestion failed'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="sidebar-footer">
        <div className="theme-toggle-container">
          <button className="theme-toggle-btn" onClick={toggleTheme} title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}>
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            <span>{theme === 'dark' ? 'Light Mode' : 'Dark Mode'}</span>
          </button>
        </div>
        <div className="user-profile">
          <div className="avatar">D</div>
          <div className="user-info">
            <span className="user-name">Dr. Developer</span>
            <span className="user-role">Admin</span>
          </div>
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
