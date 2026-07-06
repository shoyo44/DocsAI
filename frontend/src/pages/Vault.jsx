import React, { useState, useRef } from 'react';
import { UploadCloud, File, AlertCircle, Loader, Trash2, Clock, CheckCircle2, XCircle } from 'lucide-react';
import { useApp } from '../context/AppContext';
import './Vault.css';

const Vault = () => {
  const [dragActive, setDragActive] = useState(false);
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  
  const { 
    vertical, 
    setVertical, 
    documents, 
    loadingDocs, 
    fetchDocuments, 
    activeJobs, 
    uploadDocument,
    tenantId,
    apiBase
  } = useApp();

  const inputRef = useRef(null);

  const handleDelete = async (docId) => {
    if (!window.confirm("Are you sure you want to delete this document? All associated chunks and graph nodes will be removed.")) return;
    
    try {
      const response = await fetch(`${apiBase}/documents/${docId}?tenant_id=${tenantId}`, {
        method: 'DELETE'
      });
      if (response.ok) {
        fetchDocuments();
      } else {
        const data = await response.json().catch(() => ({}));
        setError(`Delete failed: ${data.detail || response.statusText}`);
      }
    } catch (err) {
      console.error("Delete failed:", err);
      setError(`Delete failed: ${err.message}`);
    }
  };

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFile(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      handleFile(e.target.files[0]);
    }
  };

  const handleFile = (selectedFile) => {
    const ext = selectedFile.name.split('.').pop().toLowerCase();
    const supportedExts = ['pdf', 'png', 'jpg', 'jpeg', 'txt', 'csv', 'docx'];
    if (!supportedExts.includes(ext)) {
      setError("Unsupported file type. Supported: PDF, PNG, JPG, TXT, CSV, DOCX");
      return;
    }
    setFile(selectedFile);
    setError(null);
  };

  const onUpload = async () => {
    if (!file) return;

    setUploading(true);
    setError(null);

    try {
      await uploadDocument(file, vertical);
      setFile(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  };

  const handleClearAll = async () => {
    if (!window.confirm("WARNING: This will delete ALL documents in your vault. This action cannot be undone. Are you sure?")) return;
    
    try {
      await Promise.all(
        documents.map(doc =>
          fetch(`${apiBase}/documents/${doc.id}?tenant_id=${tenantId}`, {
            method: 'DELETE'
          })
        )
      );
      fetchDocuments();
    } catch (err) {
      console.error("Clear all failed:", err);
      setError(`Clear all failed: ${err.message}`);
    }
  };

  return (
    <div className="vault-container animate-fade-in">

      <div className="vault-header">
        <h1>Document Vault</h1>
        <p className="subtitle">Manage your knowledge base and index documents into the DocsAI GraphStore.</p>
      </div>

      <div className="vault-content">
        <div className="upload-section glass-panel">
          <div className="vertical-selector">
            <label>Select Vertical Logic:</label>
            <select value={vertical} onChange={(e) => setVertical(e.target.value)}>
              <option value="university">University Papers</option>
              <option value="law">Legal Contracts</option>
              <option value="startup">Startup & VC</option>
              <option value="compliance">Compliance Regulations</option>
              <option value="hr">HR Policies</option>
            </select>
          </div>

          <div 
            className={`dropzone ${dragActive ? 'active' : ''}`}
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            onClick={() => inputRef.current.click()}
          >
            <input 
              ref={inputRef} 
              type="file" 
              accept=".pdf,.png,.jpg,.jpeg,.txt,.csv,.docx" 
              onChange={handleChange} 
              style={{ display: "none" }} 
            />
            
            <UploadCloud size={48} className="dropzone-icon" />
            <h3>Drag & Drop a file here</h3>
            <p>PDF, DOCX, TXT, CSV, PNG, JPG supported</p>
          </div>

          {file && (
            <div className="file-preview animate-fade-in">
              <File size={24} className="file-icon" />
              <div className="file-info">
                <span className="file-name">{file.name}</span>
                <span className="file-size">{(file.size / 1024 / 1024).toFixed(2)} MB</span>
              </div>
              <button 
                className="primary-button upload-btn hover-lift" 
                onClick={(e) => { e.stopPropagation(); onUpload(); }}
                disabled={uploading}
              >
                {uploading ? <><Loader className="spin" size={18} /> Processing...</> : "Ingest Document"}
              </button>
            </div>
          )}

          {error && (
            <div className="alert error animate-fade-in">
              <AlertCircle size={20} />
              <span>{error}</span>
            </div>
          )}

          {activeJobs.length > 0 && (
            <div className="ongoing-jobs-panel animate-fade-in">
              <h4 className="ongoing-title">Ongoing Ingestions</h4>
              <div className="ongoing-jobs-list">
                {activeJobs.map(job => (
                  <div key={job.id} className={`ongoing-job-card ${job.status}`}>
                    <div className="ongoing-job-header">
                      <div className="ongoing-job-title-row">
                        {job.status === 'pending' && <Clock size={16} className="text-tertiary" />}
                        {job.status === 'running' && <Loader size={16} className="spin text-accent" />}
                        {job.status === 'completed' && <CheckCircle2 size={16} className="text-success" />}
                        {job.status === 'failed' && <XCircle size={16} className="text-error" />}
                        <span className="job-name-text" title={job.name}>{job.name}</span>
                      </div>
                      <span className={`status-badge ${job.status}`}>{job.status}</span>
                    </div>
                    
                    {job.status === 'running' && (
                      <div className="ongoing-job-progress">
                        <div className="progress-bar-fill running"></div>
                      </div>
                    )}
                    
                    <div className="ongoing-job-footer">
                      <span className="job-vertical-tag">{job.vertical}</span>
                      {job.status === 'completed' && (
                        <span className="job-desc-success">Created {job.chunksCreated} chunks.</span>
                      )}
                      {job.status === 'failed' && (
                        <span className="job-desc-error" title={job.error}>Failed: {job.error}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="docs-section glass-panel">
          <div className="section-header-row">
            <h3>Your Documents</h3>
            {documents.length > 0 && (
              <button className="clear-all-btn" onClick={handleClearAll}>
                <Trash2 size={14} /> Clear All
              </button>
            )}
          </div>

          {loadingDocs ? (
            <div className="loading-state"><Loader className="spin" /> Loading vault...</div>
          ) : documents.length === 0 ? (
            <p className="empty-state">No documents found. Upload one to get started!</p>
          ) : (
            <div className="doc-list">
              {documents.map(doc => (
                <div key={doc.id} className="doc-item animate-slide-up">
                  <div className="doc-icon"><File size={18} /></div>
                  <div className="doc-details">
                    <span className="doc-name">{doc.name}</span>
                    <span className="doc-meta">{doc.vertical} • {doc.chunks_count} chunks</span>
                  </div>
                  <button className="delete-btn" onClick={() => handleDelete(doc.id)}>
                    <Trash2 size={18} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Vault;
