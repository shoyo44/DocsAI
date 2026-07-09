import React, { useState, useRef } from 'react';
import {
  UploadCloud, File, AlertCircle, Loader, Trash2, Clock,
  CheckCircle2, XCircle, Sparkles, ChevronDown, ShieldCheck,
  BookOpen, Briefcase, Scale, Users, Tag, Target, FileText,
  ArrowRight, Info, RefreshCw,
} from 'lucide-react';
import { useApp } from '../context/AppContext';
import { useToast } from '../components/Toast';
import './Vault.css';

// ── Vertical metadata ──────────────────────────────────────────────────────────
const VERTICAL_META = {
  university: {
    label: 'University / Research',
    icon: BookOpen,
    color: '#6366f1',
    bg: 'rgba(99,102,241,0.12)',
    border: 'rgba(99,102,241,0.35)',
    desc: 'Academic papers, journals, research studies',
  },
  law: {
    label: 'Legal Contract',
    icon: Scale,
    color: '#f59e0b',
    bg: 'rgba(245,158,11,0.12)',
    border: 'rgba(245,158,11,0.35)',
    desc: 'NDAs, legal agreements, contracts, clauses',
  },
  startup: {
    label: 'Startup / VC',
    icon: Briefcase,
    color: '#10b981',
    bg: 'rgba(16,185,129,0.12)',
    border: 'rgba(16,185,129,0.35)',
    desc: 'Pitch decks, term sheets, VC documents',
  },
  compliance: {
    label: 'Compliance',
    icon: ShieldCheck,
    color: '#3b82f6',
    bg: 'rgba(59,130,246,0.12)',
    border: 'rgba(59,130,246,0.35)',
    desc: 'Regulatory standards, audit reports, policies',
  },
  hr: {
    label: 'HR Policies',
    icon: Users,
    color: '#ec4899',
    bg: 'rgba(236,72,153,0.12)',
    border: 'rgba(236,72,153,0.35)',
    desc: 'Employee handbooks, HR policies, onboarding docs',
  },
};

const CONFIDENCE_STYLE = {
  HIGH:   { color: '#10b981', bg: 'rgba(16,185,129,0.12)', label: 'High confidence' },
  MEDIUM: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', label: 'Medium confidence' },
  LOW:    { color: '#ef4444', bg: 'rgba(239,68,68,0.12)',  label: 'Low confidence'  },
};

// ── Detecting phases ───────────────────────────────────────────────────────────
const DETECT_PHASES = [
  { id: 0, label: 'Extracting text from document…' },
  { id: 1, label: 'Phase 1 — Summarising document…' },
  { id: 2, label: 'Phase 2 — Classifying document type…' },
];

// ── Component ─────────────────────────────────────────────────────────────────
const Vault = () => {
  const toast = useToast();
  const [dragActive, setDragActive]             = useState(false);
  const [file, setFile]                         = useState(null);
  const [uploading, setUploading]               = useState(false);
  const [error, setError]                       = useState(null);

  // Detection state
  const [detecting, setDetecting]               = useState(false);
  const [detectPhase, setDetectPhase]           = useState(0);
  const [detection, setDetection]               = useState(null);
  const [confirmedVertical, setConfirmedVertical] = useState(null);
  const [showOverride, setShowOverride]         = useState(false);
  const [showSummaryDetail, setShowSummaryDetail] = useState(false);

  const {
    vertical, setVertical,
    documents, loadingDocs, fetchDocuments,
    activeJobs, uploadDocument,
    tenantId, apiBase,
  } = useApp();

  const inputRef    = useRef(null);
  const phaseTimer  = useRef(null);

  // ── Phase ticker (cosmetic progress while waiting) ──────────────────────────
  const startPhaseTimer = () => {
    setDetectPhase(0);
    let phase = 0;
    phaseTimer.current = setInterval(() => {
      phase = Math.min(phase + 1, DETECT_PHASES.length - 1);
      setDetectPhase(phase);
    }, 2200);
  };
  const stopPhaseTimer = () => {
    clearInterval(phaseTimer.current);
    phaseTimer.current = null;
  };

  // ── Detect vertical via DocumentClassifierAgent backend ────────────────────
  const detectVertical = async (selectedFile) => {
    setDetecting(true);
    setDetection(null);
    setConfirmedVertical(null);
    setShowOverride(false);
    setShowSummaryDetail(false);
    startPhaseTimer();

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);

      const res = await fetch(
        `${apiBase}/detect-vertical?tenant_id=${tenantId}`,
        { method: 'POST', body: formData }
      );

      if (!res.ok) throw new Error(`Detection failed: ${res.statusText}`);
      const data = await res.json();
      setDetection(data);
      setConfirmedVertical(data.vertical);
      setVertical(data.vertical);
    } catch (err) {
      console.error('Auto-detect failed:', err);
      setDetection({
        vertical: vertical || 'university',
        confidence: 'LOW',
        ai_suggestion: 'Could not reach the detection service. Please select the document type manually.',
        summary: {},
        meta: {},
      });
      setConfirmedVertical(vertical || 'university');
    } finally {
      stopPhaseTimer();
      setDetecting(false);
    }
  };

  // ── File handling ──────────────────────────────────────────────────────────
  const handleFile = (selectedFile) => {
    const ext = selectedFile.name.split('.').pop().toLowerCase();
    const supported = ['pdf', 'png', 'jpg', 'jpeg', 'txt', 'csv', 'docx'];
    if (!supported.includes(ext)) {
      setError('Unsupported file type. Supported: PDF, PNG, JPG, TXT, CSV, DOCX');
      return;
    }
    setFile(selectedFile);
    setError(null);
    detectVertical(selectedFile);
  };

  const handleDrag = (e) => {
    e.preventDefault(); e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') setDragActive(true);
    else if (e.type === 'dragleave') setDragActive(false);
  };

  const handleDrop = (e) => {
    e.preventDefault(); e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files?.[0]) handleFile(e.dataTransfer.files[0]);
  };

  const handleChange = (e) => {
    e.preventDefault();
    if (e.target.files?.[0]) handleFile(e.target.files[0]);
  };

  // ── Override ───────────────────────────────────────────────────────────────
  // NOTE: Do NOT call setVertical here — it triggers an AppContext re-render
  // which re-applies animate-fade-in on the detection card, making it look like
  // the selection didn't register. confirmedVertical is the sole source of truth
  // for the ingest call; setVertical only needs to be set on final confirm.
  const handleOverride = (v) => {
    setConfirmedVertical(v);
    // Close dropdown after a brief delay so user sees the checkmark move
    setTimeout(() => setShowOverride(false), 300);
  };

  // ── Re-detect ──────────────────────────────────────────────────────────────
  const handleRedetect = () => {
    if (file) detectVertical(file);
  };

  // ── Ingest ─────────────────────────────────────────────────────────────────
  const onUpload = async () => {
    if (!file || !confirmedVertical) return;
    setUploading(true);
    setError(null);
    try {
      // Sync context vertical with confirmed choice right before upload
      setVertical(confirmedVertical);
      await uploadDocument(file, confirmedVertical);
      toast.success("Ingestion Started", `"${file.name}" is being processed in the background.`);
      setFile(null);
      setDetection(null);
      setConfirmedVertical(null);
      setShowSummaryDetail(false);
    } catch (err) {
      setError(err.message);
      toast.error("Upload Failed", err.message);
    } finally {
      setUploading(false);
    }
  };

  // ── Delete ─────────────────────────────────────────────────────────────────
  const handleDelete = async (docId) => {
    if (!window.confirm('Delete this document? All associated chunks and graph nodes will be removed.')) return;
    try {
      const res = await fetch(`${apiBase}/documents/${docId}?tenant_id=${tenantId}`, { method: 'DELETE' });
      if (res.ok) {
        toast.success("Document Purged", "Document and associated indexing nodes deleted.");
        fetchDocuments();
      } else {
        const data = await res.json().catch(() => ({}));
        const errMsg = `Delete failed: ${data.detail || res.statusText}`;
        setError(errMsg);
        toast.error("Deletion Failed", errMsg);
      }
    } catch (err) {
      const errMsg = `Delete failed: ${err.message}`;
      setError(errMsg);
      toast.error("Deletion Failed", errMsg);
    }
  };

  const handleClearAll = async () => {
    if (!window.confirm('WARNING: This will delete ALL documents. This cannot be undone.')) return;
    try {
      await Promise.all(documents.map(doc =>
        fetch(`${apiBase}/documents/${doc.id}?tenant_id=${tenantId}`, { method: 'DELETE' })
      ));
      toast.success("Vault Cleared", "All documents purged successfully.");
      fetchDocuments();
    } catch (err) {
      setError(`Clear all failed: ${err.message}`);
      toast.error("Purge Failed", err.message);
    }
  };

  // ── Computed helpers ───────────────────────────────────────────────────────
  const activeMeta   = VERTICAL_META[confirmedVertical] || VERTICAL_META.university;
  const detectedMeta = detection ? (VERTICAL_META[detection.vertical] || VERTICAL_META.university) : null;
  const confStyle    = detection ? (CONFIDENCE_STYLE[detection.confidence] || CONFIDENCE_STYLE.MEDIUM) : null;
  const summary      = detection?.summary || {};
  const altMeta      = detection?.alternative_vertical
    ? (VERTICAL_META[detection.alternative_vertical] || null)
    : null;
  const ActiveIcon   = activeMeta.icon;
  const isOverridden = detection && confirmedVertical !== detection.vertical;

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="vault-container animate-fade-in">

      <div className="vault-header">
        <h1>Document Vault</h1>
        <p className="subtitle">
          Upload a document — DocsAI will automatically summarise and classify its type, then ask for your confirmation before indexing.
        </p>
      </div>

      <div className="vault-content">
        <div className="upload-section glass-panel">

          {/* ── Drop zone ── */}
          {!file && (
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
                style={{ display: 'none' }}
              />
              <UploadCloud size={48} className="dropzone-icon" />
              <h3>Drag &amp; Drop a file here</h3>
              <p>PDF, DOCX, TXT, CSV, PNG, JPG supported</p>
            </div>
          )}

          {/* ── Hidden input when file is selected (for "change file") ── */}
          {file && (
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.txt,.csv,.docx"
              onChange={handleChange}
              style={{ display: 'none' }}
            />
          )}

          {/* ── Detecting spinner ── */}
          {detecting && (
            <div className="detection-card detecting animate-fade-in">
              <div className="detection-spinner-row">
                <Loader size={20} className="spin" style={{ color: 'var(--accent-primary)' }} />
                <div className="detection-phases">
                  <span className="detection-analyzing-text">
                    {DETECT_PHASES[detectPhase].label}
                  </span>
                  <div className="phase-dots">
                    {DETECT_PHASES.map((p) => (
                      <span
                        key={p.id}
                        className={`phase-dot ${p.id <= detectPhase ? 'active' : ''}`}
                      />
                    ))}
                  </div>
                </div>
              </div>
              <div className="detection-file-name" style={{ color: 'var(--text-tertiary)', fontSize: '0.8rem' }}>
                {file?.name}
              </div>
            </div>
          )}

          {/* ── Detection result card ── */}
          {!detecting && detection && file && (
            <div
              className="detection-card"
              style={{ borderColor: activeMeta.border, background: activeMeta.bg, transition: 'border-color 0.3s ease, background 0.3s ease' }}
            >
              {/* Header: AI badge + confidence */}
              <div className="detection-header">
                <div className="detection-ai-badge">
                  <Sparkles size={12} />
                  <span>AI Classified</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  {isOverridden && (
                    <span className="override-chip">Manually overridden</span>
                  )}
                  <span
                    className="detection-confidence-badge"
                    style={{ color: confStyle.color, background: confStyle.bg }}
                  >
                    {confStyle.label}
                  </span>
                </div>
              </div>

              {/* Detected type */}
              <div className="detection-type-row">
                <div
                  className="detection-type-icon-wrap"
                  style={{ background: activeMeta.bg, borderColor: activeMeta.border }}
                >
                  <ActiveIcon size={24} style={{ color: activeMeta.color }} />
                </div>
                <div className="detection-type-info">
                  <span className="detection-type-label" style={{ color: activeMeta.color }}>
                    {activeMeta.label}
                  </span>
                  {summary.document_type && (
                    <span className="detection-doc-type-sub">
                      Detected as: <strong>{summary.document_type}</strong>
                    </span>
                  )}
                </div>
              </div>

              {/* AI Suggestion paragraph */}
              {detection.ai_suggestion && (
                <div className="ai-suggestion-block" style={{ borderLeftColor: activeMeta.color }}>
                  <div className="ai-suggestion-header">
                    <Sparkles size={13} style={{ color: activeMeta.color }} />
                    <span>AI Suggestion</span>
                  </div>
                  <p className="ai-suggestion-text">{detection.ai_suggestion}</p>
                </div>
              )}

              {/* Alternative vertical hint */}
              {altMeta && !isOverridden && (
                <div className="alt-vertical-hint">
                  <Info size={13} />
                  <span>
                    Could also be&nbsp;
                    <strong style={{ color: altMeta.color }}>{altMeta.label}</strong>
                    &nbsp;— use "Change type" below if needed.
                  </span>
                </div>
              )}

              {/* Document summary (collapsible) */}
              {(summary.main_topics?.length > 0 || summary.key_entities?.length > 0 || summary.intended_audience) && (
                <div className="summary-section">
                  <button
                    className="summary-toggle"
                    onClick={() => setShowSummaryDetail(v => !v)}
                  >
                    <FileText size={13} />
                    <span>Document Summary</span>
                    <ChevronDown
                      size={13}
                      style={{ transform: showSummaryDetail ? 'rotate(180deg)' : 'rotate(0)', transition: 'transform 0.2s' }}
                    />
                  </button>

                  {showSummaryDetail && (
                    <div className="summary-detail animate-fade-in">
                      {summary.intended_audience && (
                        <div className="summary-row">
                          <Target size={12} className="summary-row-icon" />
                          <span className="summary-row-label">Audience:</span>
                          <span className="summary-row-value">{summary.intended_audience}</span>
                        </div>
                      )}
                      {summary.language_style && (
                        <div className="summary-row">
                          <FileText size={12} className="summary-row-icon" />
                          <span className="summary-row-label">Style:</span>
                          <span className="summary-row-value">{summary.language_style}</span>
                        </div>
                      )}
                      {summary.main_topics?.length > 0 && (
                        <div className="summary-row summary-row-wrap">
                          <Tag size={12} className="summary-row-icon" />
                          <span className="summary-row-label">Topics:</span>
                          <div className="summary-tags">
                            {summary.main_topics.map((t, i) => (
                              <span key={i} className="summary-tag" style={{ background: activeMeta.bg, color: activeMeta.color }}>
                                {t}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {summary.key_entities?.length > 0 && (
                        <div className="summary-row summary-row-wrap">
                          <Tag size={12} className="summary-row-icon" />
                          <span className="summary-row-label">Entities:</span>
                          <div className="summary-tags">
                            {summary.key_entities.slice(0, 8).map((e, i) => (
                              <span key={i} className="summary-tag entity-tag">
                                {e}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {summary.excerpt_highlights?.length > 0 && (
                        <div className="summary-excerpts">
                          <span className="summary-row-label">Key excerpts:</span>
                          {summary.excerpt_highlights.map((ex, i) => (
                            <blockquote key={i} className="summary-excerpt">"{ex}"</blockquote>
                          ))}
                        </div>
                      )}
                      {detection.meta?.pages_read != null && (
                        <div className="summary-meta-row">
                          <span>📄 {detection.meta.pages_read} page(s) read</span>
                          {detection.meta.chars_used > 0 && (
                            <span>· {detection.meta.chars_used.toLocaleString()} chars analysed</span>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* File info row */}
              <div className="detection-file-row">
                <File size={14} style={{ color: 'var(--text-tertiary)' }} />
                <span className="detection-file-name">{file.name}</span>
                <span className="detection-file-size">
                  {(file.size / 1024 / 1024).toFixed(2)} MB
                </span>
              </div>

              {/* Override picker */}
              <div className="detection-actions">
                <div className="override-wrapper">
                  <button
                    className="override-toggle"
                    onClick={() => setShowOverride(v => !v)}
                  >
                    <span>Not right? Change type</span>
                    <ChevronDown
                      size={13}
                      style={{ transform: showOverride ? 'rotate(180deg)' : 'rotate(0)', transition: 'transform 0.2s' }}
                    />
                  </button>

                  {showOverride && (
                    <div className="override-dropdown animate-fade-in">
                      {Object.entries(VERTICAL_META).map(([key, meta]) => {
                        const Icon = meta.icon;
                        return (
                          <button
                            key={key}
                            className={`override-option ${confirmedVertical === key ? 'active' : ''}`}
                            onClick={() => handleOverride(key)}
                            style={confirmedVertical === key ? { background: meta.bg, borderColor: meta.border } : {}}
                          >
                            <Icon size={15} style={{ color: meta.color }} />
                            <div className="override-option-text">
                              <span className="override-option-label">{meta.label}</span>
                              <span className="override-option-desc">{meta.desc}</span>
                            </div>
                            {confirmedVertical === key && (
                              <CheckCircle2 size={13} style={{ color: meta.color, marginLeft: 'auto', flexShrink: 0 }} />
                            )}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* CTA row */}
                <div className="detection-cta-row">
                  <button
                    className="ghost-button"
                    title="Re-run detection"
                    onClick={handleRedetect}
                    disabled={detecting}
                  >
                    <RefreshCw size={14} />
                    Re-detect
                  </button>
                  <button
                    className="ghost-button"
                    onClick={() => { setFile(null); setDetection(null); setConfirmedVertical(null); inputRef.current.click(); }}
                  >
                    Change file
                  </button>
                  <button
                    className="primary-button confirm-ingest-btn hover-lift"
                    onClick={onUpload}
                    disabled={uploading}
                  >
                    {uploading
                      ? <><Loader className="spin" size={16} /> Processing…</>
                      : <><CheckCircle2 size={16} /> Confirm &amp; Ingest</>
                    }
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="alert error animate-fade-in">
              <AlertCircle size={20} />
              <span>{error}</span>
            </div>
          )}

          {/* Ongoing ingestions */}
          {activeJobs.length > 0 && (
            <div className="ongoing-jobs-panel animate-fade-in">
              <h4 className="ongoing-title">Ongoing Ingestions</h4>
              <div className="ongoing-jobs-list">
                {activeJobs.map(job => (
                  <div key={job.id} className={`ongoing-job-card ${job.status}`}>
                    <div className="ongoing-job-header">
                      <div className="ongoing-job-title-row">
                        {job.status === 'pending'   && <Clock size={16} className="text-tertiary" />}
                        {job.status === 'running'   && <Loader size={16} className="spin text-accent" />}
                        {job.status === 'completed' && <CheckCircle2 size={16} className="text-success" />}
                        {job.status === 'failed'    && <XCircle size={16} className="text-error" />}
                        <span className="job-name-text" title={job.name}>{job.name}</span>
                      </div>
                      <span className={`status-badge ${job.status}`}>{job.status}</span>
                    </div>
                    {job.status === 'running' && (
                      <div className="ongoing-job-progress">
                        <div className="progress-bar-fill running" />
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

        {/* ── Documents panel ── */}
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
            <div className="skeleton-list">
              {[1, 2, 3].map(i => (
                <div key={i} className="skeleton-item">
                  <div className="skeleton-icon" />
                  <div className="skeleton-details">
                    <div className="skeleton-title" />
                    <div className="skeleton-meta" />
                  </div>
                </div>
              ))}
            </div>
          ) : documents.length === 0 ? (
            <p className="empty-state">No documents found. Upload one to get started!</p>
          ) : (
            <div className="doc-list">
              {documents.map(doc => {
                const meta = VERTICAL_META[doc.vertical] || VERTICAL_META.university;
                const Icon = meta.icon;
                return (
                  <div key={doc.id} className="doc-item animate-slide-up">
                    <div className="doc-icon" style={{ color: meta.color }}>
                      <Icon size={18} />
                    </div>
                    <div className="doc-details">
                      <span className="doc-name">{doc.name}</span>
                      <span className="doc-meta">
                        <span className="doc-vertical-pill" style={{ background: meta.bg, color: meta.color }}>
                          {meta.label}
                        </span>
                        &nbsp;•&nbsp;{doc.chunks_count} chunks
                      </span>
                    </div>
                    <button className="delete-btn" onClick={() => handleDelete(doc.id)}>
                      <Trash2 size={18} />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Vault;
