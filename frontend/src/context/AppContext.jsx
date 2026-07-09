import React, { createContext, useContext, useState, useEffect } from 'react';
import { API_BASE, TENANT_ID, WS_BASE } from '../config';

const AppContext = createContext(null);

export const AppContextProvider = ({ children }) => {
  const [vertical, setVertical] = useState('university');
  const [documents, setDocuments] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [activeJobs, setActiveJobs] = useState([]);
  const theme = 'light';

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', 'light');
    localStorage.setItem('theme', 'light');
  }, []);

  const toggleTheme = () => {};
  
  // Gmail login simulation state
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem('auth_user');
    return saved ? JSON.parse(saved) : null;
  });

  const loginWithGoogle = (userData) => {
    setUser(userData);
    localStorage.setItem('auth_user', JSON.stringify(userData));
  };

  const logout = () => {
    setUser(null);
    localStorage.removeItem('auth_user');
  };
  
  // Pipeline threshold variables persisted in localStorage
  const [temperature, setTemperature] = useState(() => {
    const saved = localStorage.getItem('rag_temperature');
    return saved !== null ? parseFloat(saved) : 0.05;
  });
  const [topK, setTopK] = useState(() => {
    const saved = localStorage.getItem('rag_topK');
    return saved !== null ? parseInt(saved, 10) : 10;
  });
  const [scoreFloor, setScoreFloor] = useState(() => {
    const saved = localStorage.getItem('rag_scoreFloor');
    return saved !== null ? parseFloat(saved) : 0.40;
  });

  useEffect(() => {
    localStorage.setItem('rag_temperature', temperature.toString());
  }, [temperature]);

  useEffect(() => {
    localStorage.setItem('rag_topK', topK.toString());
  }, [topK]);

  useEffect(() => {
    localStorage.setItem('rag_scoreFloor', scoreFloor.toString());
  }, [scoreFloor]);

  const tenantId = TENANT_ID;
  const apiBase = API_BASE;
  const wsBase = WS_BASE;

  const fetchDocuments = async () => {
    try {
      const response = await fetch(`${apiBase}/documents?tenant_id=${tenantId}`);
      if (response.ok) {
        const data = await response.json();
        setDocuments(data.documents || []);
      }
    } catch (err) {
      console.error("Failed to fetch documents:", err);
    } finally {
      setLoadingDocs(false);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, []);

  const addJob = (job) => {
    setActiveJobs(prev => [job, ...prev]);
  };

  const updateJob = (jobId, updates) => {
    setActiveJobs(prev => prev.map(job => 
      job.id === jobId ? { ...job, ...updates } : job
    ));
  };

  const pollJobStatus = (jobId) => {
    const interval = setInterval(async () => {
      try {
        const statusRes = await fetch(`${apiBase}/jobs/${jobId}`);
        if (!statusRes.ok) throw new Error("Failed to check status");
        
        const statusData = await statusRes.json();

        if (statusData.status === 'completed') {
          clearInterval(interval);
          updateJob(jobId, {
            status: 'completed',
            chunksCreated: statusData.result?.chunks_created ?? '?',
            completedAt: Date.now()
          });
          // Refresh document list
          fetchDocuments();
          
          // Automatically clear completed job details from the sidebar after 10 seconds
          setTimeout(() => {
            setActiveJobs(prev => prev.filter(job => job.id !== jobId));
          }, 10000);

        } else if (statusData.status === 'failed') {
          clearInterval(interval);
          updateJob(jobId, {
            status: 'failed',
            error: statusData.error || 'Ingestion job failed',
            completedAt: Date.now()
          });
        } else if (statusData.status === 'running') {
          updateJob(jobId, { status: 'running' });
        }
      } catch (err) {
        // network or server issues — keep polling for a few retries, or fail
        console.error("Error polling job status:", err);
      }
    }, 2000);
  };

  const uploadDocument = async (file, uploadVertical) => {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(
      `${apiBase}/upload?tenant_id=${tenantId}&vertical=${uploadVertical}`,
      { method: 'POST', body: formData }
    );

    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Upload failed");

    const newJob = {
      id: data.job_id,
      name: file.name,
      vertical: uploadVertical,
      status: 'pending',
      createdAt: Date.now(),
      chunksCreated: null,
      error: null
    };

    addJob(newJob);
    pollJobStatus(data.job_id);
    return data;
  };

  return (
    <AppContext.Provider value={{
      vertical,
      setVertical,
      documents,
      loadingDocs,
      fetchDocuments,
      activeJobs,
      uploadDocument,
      tenantId,
      apiBase,
      wsBase,
      temperature,
      setTemperature,
      topK,
      setTopK,
      scoreFloor,
      setScoreFloor,
      user,
      loginWithGoogle,
      logout,
      theme,
      toggleTheme
    }}>
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error("useApp must be used within AppContextProvider");
  }
  return context;
};
