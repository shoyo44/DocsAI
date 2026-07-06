import React, { createContext, useContext, useState, useEffect } from 'react';
import { API_BASE, TENANT_ID, WS_BASE } from '../config';

const AppContext = createContext(null);

export const AppContextProvider = ({ children }) => {
  const [vertical, setVertical] = useState('university');
  const [documents, setDocuments] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [activeJobs, setActiveJobs] = useState([]);

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
      wsBase
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
