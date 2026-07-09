import React, { useState, useEffect, useRef } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { MessageSquare, Files, Settings, Activity, Loader, CheckCircle2, XCircle, Clock, Sun, Moon, Menu, X, Keyboard, LogOut, ChevronUp } from 'lucide-react';
import { useApp } from '../context/AppContext';
import { useToast } from './Toast';
import logoUrl from '../assets/logo.png';
import './Sidebar.css';

const Sidebar = () => {
  const { activeJobs, user, logout, theme, toggleTheme } = useApp();
  const toast = useToast();
  const [collapsed, setCollapsed] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const location = useLocation();
  const navRef = useRef(null);
  const dropdownRef = useRef(null);
  const [indicatorStyle, setIndicatorStyle] = useState({});

  // Close dropdown on click outside
  useEffect(() => {
    const handleOutsideClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  // Keyboard shortcut: Ctrl+/ to toggle sidebar
  useEffect(() => {
    const handleKey = (e) => {
      if (e.ctrlKey && e.key === '/') {
        e.preventDefault();
        setCollapsed(prev => !prev);
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, []);

  const navItems = [
    { name: 'Agent Chat', path: '/chat', icon: MessageSquare },
    { name: 'Document Vault', path: '/vault', icon: Files },
    { name: 'Analytics', path: '/analytics', icon: Activity },
    { name: 'History', path: '/history', icon: Clock },
    { name: 'Settings', path: '/settings', icon: Settings },
  ];

  // Animated indicator positioning
  useEffect(() => {
    if (!navRef.current) return;
    const activeEl = navRef.current.querySelector('.nav-item.active');
    if (activeEl) {
      setIndicatorStyle({
        top: activeEl.offsetTop,
        height: activeEl.offsetHeight,
      });
    }
  }, [location.pathname]);

  return (
    <>
      {/* Mobile hamburger */}
      <button
        className="sidebar-mobile-toggle"
        onClick={() => setCollapsed(prev => !prev)}
        aria-label="Toggle sidebar"
      >
        {collapsed ? <X size={22} /> : <Menu size={22} />}
      </button>

      <aside className={`sidebar glass-panel ${collapsed ? 'sidebar-open-mobile' : ''}`}>
        <div className="sidebar-header">
          <img src={logoUrl} alt="DocsAI Logo" className="sidebar-logo-icon" />
          <h2>DocsAI</h2>
        </div>
        
        <nav className="sidebar-nav" ref={navRef}>
          {/* Sliding indicator */}
          <div className="nav-indicator" style={{ top: indicatorStyle.top, height: indicatorStyle.height }} />
          
          {navItems.map((item) => (
            <NavLink 
              to={item.path} 
              key={item.name}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
              onClick={() => {
                // Close mobile sidebar on nav
                if (window.innerWidth < 768) setCollapsed(false);
              }}
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

        <div className="sidebar-footer" ref={dropdownRef}>
          {dropdownOpen && (
            <div className="profile-dropdown-menu glass-panel animate-slide-up">
              <div className="dropdown-user-header">
                <span className="dropdown-user-name">{user?.name || "Guest User"}</span>
                <span className="dropdown-user-email">{user?.email || "guest@docsai.com"}</span>
              </div>
              <div className="dropdown-divider" />
              <div className="dropdown-item dropdown-shortcut-item">
                <Keyboard size={13} />
                <span>Ctrl+/ to Collapse</span>
              </div>
              <div className="dropdown-divider" />
              <button 
                className="dropdown-item logout-action" 
                onClick={() => {
                  logout();
                  setDropdownOpen(false);
                  toast.info("Logged Out", "Redirected to login screen.");
                }}
              >
                <LogOut size={15} />
                <span>Log Out</span>
              </button>
            </div>
          )}

          <div 
            className={`user-profile-trigger ${dropdownOpen ? 'active' : ''} hover-lift`}
            onClick={() => setDropdownOpen(prev => !prev)}
            role="button"
            tabIndex={0}
          >
            {user?.avatar ? (
              <img src={user.avatar} alt="Avatar" className="user-avatar-img" />
            ) : (
              <div className="avatar">{user?.name ? user.name[0].toUpperCase() : 'G'}</div>
            )}
            <div className="user-info">
              <span className="user-name" title={user?.name || "Guest"}>{user?.name || "Guest"}</span>
              <span className="user-role" title={user?.email || "Guest User"}>{user?.role || "Admin"}</span>
            </div>
            <ChevronUp size={16} className={`chevron-icon ${dropdownOpen ? 'rotate-180' : ''}`} />
          </div>
        </div>
      </aside>
    </>
  );
};

export default Sidebar;

