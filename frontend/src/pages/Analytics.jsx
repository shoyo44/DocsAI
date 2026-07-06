import React, { useState, useEffect, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { Activity, Database, Cpu, Globe, Maximize2, RotateCcw, FileText, Layers, TrendingUp, AlertCircle, Loader, ChevronRight, BookOpen } from 'lucide-react';
import { useApp } from '../context/AppContext';
import './Analytics.css';

const Analytics = () => {
  const { documents, tenantId, apiBase } = useApp();
  const [graphData, setGraphData]   = useState({ nodes: [], links: [] });
  const [stats, setStats]           = useState(null);
  const [recent, setRecent]         = useState([]);
  const [loading, setLoading]       = useState(true);
  const [statsLoading, setStatsLoading] = useState(true);
  const [error, setError]           = useState(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 480 });
  const [selectedNode, setSelectedNode] = useState(null);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [chunks, setChunks]           = useState([]);
  const [loadingChunks, setLoadingChunks] = useState(false);
  const [errorChunks, setErrorChunks] = useState(null);
  const containerRef = React.useRef(null);
  const fgRef        = React.useRef(null);

  const fetchAll = useCallback(async () => {
    // Graph nodes
    try {
      setLoading(true);
      const res  = await fetch(`${apiBase}/analytics/${tenantId}/graph`);
      const data = await res.json();
      setGraphData(data);
    } catch (e) {
      setError('Failed to load knowledge graph.');
    } finally {
      setLoading(false);
    }

    // Dashboard stats
    try {
      setStatsLoading(true);
      const res  = await fetch(`${apiBase}/analytics/dashboard?tenant_id=${tenantId}`);
      const data = await res.json();
      setStats(data);
    } catch (e) {
      setStats(null);
    } finally {
      setStatsLoading(false);
    }

    // Recent queries
    try {
      const res  = await fetch(`${apiBase}/analytics/recent?tenant_id=${tenantId}&limit=6`);
      const data = await res.json();
      setRecent(data.queries || []);
    } catch (_) {}
  }, [apiBase, tenantId]);

  useEffect(() => {
    fetchAll();
    const obs = new ResizeObserver(() => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.offsetWidth - 32,
          height: 480,
        });
      }
    });
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, [fetchAll]);

  useEffect(() => {
    if (fgRef.current) {
      fgRef.current.d3Force('link').distance(80);
      fgRef.current.d3Force('charge').strength(-150);
    }
  }, [graphData]);

  const handleReset = () => {
    fgRef.current?.zoomToFit(400, 40);
  };

  const fetchDocChunks = async (doc) => {
    setSelectedDoc(doc);
    setLoadingChunks(true);
    setErrorChunks(null);
    try {
      const res = await fetch(`${apiBase}/documents/${doc.id}/chunks?tenant_id=${tenantId}`);
      if (res.ok) {
        const data = await res.json();
        setChunks(data.chunks || []);
      } else {
        throw new Error('Failed to load chunks.');
      }
    } catch (e) {
      setErrorChunks(e.message);
    } finally {
      setLoadingChunks(false);
    }
  };

  const confidenceColor = (c) => {
    if (!c) return '#8c8c8c';
    if (c === 'HIGH')   return '#51cf66';
    if (c === 'MEDIUM') return '#ffd43b';
    return '#ff6b6b';
  };

  return (
    <div className="analytics-container animate-fade-in">
      <div className="analytics-header">
        <h1>Graph Intelligence</h1>
        <p className="subtitle">Real-time Entity-Relationship Mapping · DocsAI GraphStore</p>
      </div>


      {/* Force Graph */}
      <div className="graph-overview glass-panel" ref={containerRef}>
        <div className="card-header">
          <div className="title-group">
            <Globe size={20} />
            <h3>Knowledge Graph Visualizer</h3>
            <span className="graph-badge">{graphData.nodes.length} nodes · {graphData.links.length} edges</span>
          </div>
          <div className="graph-controls">
            <button className="icon-btn" onClick={fetchAll} title="Refresh">
              <RotateCcw size={16} />
            </button>
            <button className="icon-btn" onClick={handleReset} title="Fit view">
              <Maximize2 size={16} />
            </button>
          </div>
        </div>

        <div className="graph-canvas-container">
          {error ? (
            <div className="placeholder-viz">
              <AlertCircle size={48} style={{color: '#ff6b6b'}} />
              <p>{error}</p>
            </div>
          ) : loading ? (
            <div className="placeholder-viz">
              <Activity size={48} className="pulse" />
              <p>Fetching graph nodes from GraphStore…</p>
            </div>
          ) : graphData.nodes.length === 0 ? (
            <div className="placeholder-viz">
              <Layers size={48} style={{opacity: 0.4}} />
              <p>No documents indexed yet. Upload a document to see the graph.</p>
            </div>
          ) : (
            <ForceGraph2D
              ref={fgRef}
              graphData={graphData}
              width={dimensions.width}
              height={dimensions.height}
              backgroundColor="rgba(0,0,0,0)"
              nodeLabel="name"
              nodeColor={n => n.color}
              nodeRelSize={7}
              nodeVal={n => n.val}
              linkColor={() => 'rgba(255,255,255,0.15)'}
              linkDirectionalParticles={4}
              linkDirectionalParticleWidth={2}
              linkDirectionalParticleSpeed={0.006}
              d3VelocityDecay={0.3}
              onNodeClick={node => setSelectedNode(node)}
              onEngineStop={() => fgRef.current?.zoomToFit(400, 40)}
              onNodeDragEnd={node => {
                node.fx = node.x;
                node.fy = node.y;
              }}
              nodeCanvasObjectMode={() => 'after'}
              nodeCanvasObject={(node, ctx, globalScale) => {
                if (globalScale < 1.5) return;
                const label    = node.name || '';
                const fontSize = 10 / globalScale;
                ctx.font      = `${fontSize}px Sans-Serif`;
                ctx.fillStyle = 'rgba(255,255,255,0.9)';
                ctx.textAlign  = 'center';
                ctx.fillText(label.slice(0, 20), node.x, node.y + 12);
              }}
            />
          )}
        </div>

        {selectedNode && (
          <div className="selected-node-panel animate-slide-up glass-panel">
            <div className="panel-header">
              <span className="panel-dot" style={{ backgroundColor: selectedNode.color }}></span>
              <h4>Node Inspector</h4>
              <button className="panel-close-btn" onClick={() => setSelectedNode(null)}>×</button>
            </div>
            <div className="panel-body">
              <div className="panel-row">
                <span className="label">Name:</span>
                <span className="value bold">{selectedNode.name}</span>
              </div>
              <div className="panel-row">
                <span className="label">Type:</span>
                <span className="value badge" style={{ color: selectedNode.color, border: `1px solid ${selectedNode.color}` }}>
                  {selectedNode.type || "entity"}
                </span>
              </div>
              <p className="panel-desc">
                {selectedNode.type === 'document' 
                  ? "This node represents a source knowledge document uploaded in the workspace." 
                  : "This node represents a key named entity extracted from documents to map connections."
                }
              </p>
            </div>
          </div>
        )}

        <div className="graph-legend">
          <div className="legend-item">
            <span className="dot" style={{backgroundColor: '#4dabf7'}}></span>
            <span>HR Document</span>
          </div>
          <div className="legend-item">
            <span className="dot" style={{backgroundColor: '#f06595'}}></span>
            <span>Law Document</span>
          </div>
          <div className="legend-item">
            <span className="dot" style={{backgroundColor: '#63e6be'}}></span>
            <span>Compliance</span>
          </div>
          <div className="legend-item">
            <span className="dot" style={{backgroundColor: '#ffd43b'}}></span>
            <span>Startup</span>
          </div>
          <div className="legend-item">
            <span className="dot" style={{backgroundColor: '#da77f2'}}></span>
            <span>University</span>
          </div>
          <div className="legend-item">
            <span className="dot" style={{backgroundColor: '#ff922b'}}></span>
            <span>Named Entity</span>
          </div>
        </div>
      </div>

      {/* Detailed Document Summary & Chunks Explorer in the bottom */}
      <div className="doc-chunks-explorer-container animate-slide-up" style={{ 
        marginTop: '1.5rem', 
        display: 'grid', 
        gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', 
        gap: '1.5rem' 
      }}>
        
        {/* Left Side: Document Summary List */}
        <div className="graph-overview glass-panel" style={{ margin: 0, display: 'flex', flexDirection: 'column' }}>
          <div className="card-header">
            <FileText size={20} className="text-accent" />
            <h3>Indexed Documents Inventory</h3>
          </div>
          <div className="recent-table" style={{ flex: 1, overflowY: 'auto', maxHeight: '420px' }}>
            {!documents || documents.length === 0 ? (
              <div style={{ padding: '3rem 1rem', textAlign: 'center', opacity: 0.5 }}>
                <Layers size={32} style={{ marginBottom: '0.8rem', color: 'var(--text-tertiary)' }} />
                <p>No documents uploaded yet.</p>
                <p style={{ fontSize: '0.8rem' }}>Go to the Document Vault page to upload.</p>
              </div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Document Name</th>
                    <th>Vertical</th>
                    <th>Version</th>
                    <th>Chunks</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {documents.map((doc) => (
                    <tr 
                      key={doc.id} 
                      onClick={() => fetchDocChunks(doc)}
                      style={{ 
                        cursor: 'pointer',
                        background: selectedDoc?.id === doc.id ? 'rgba(59, 130, 246, 0.08)' : 'transparent',
                        borderLeft: selectedDoc?.id === doc.id ? '3px solid var(--accent-primary)' : '3px solid transparent',
                        transition: 'background 0.2s, border-left 0.2s'
                      }}
                    >
                      <td className="query-cell" style={{ fontWeight: 500 }}>{doc.name}</td>
                      <td>
                        <span className="status-tag info" style={{ 
                          textTransform: 'uppercase', 
                          fontSize: '0.62rem', 
                          fontWeight: 'bold',
                          color: 'var(--accent-primary)',
                          background: 'rgba(59, 130, 246, 0.05)',
                          border: '1px solid rgba(59, 130, 246, 0.15)'
                        }}>{doc.vertical}</span>
                      </td>
                      <td>v{doc.version}</td>
                      <td><strong>{doc.chunks_count}</strong></td>
                      <td>
                        <ChevronRight size={16} style={{ 
                          opacity: selectedDoc?.id === doc.id ? 1 : 0.4,
                          transform: selectedDoc?.id === doc.id ? 'translateX(3px)' : 'none',
                          transition: 'transform 0.2s, opacity 0.2s',
                          color: 'var(--accent-primary)'
                        }} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Right Side: Chunk Inspector */}
        <div className="graph-overview glass-panel" style={{ margin: 0, display: 'flex', flexDirection: 'column' }}>
          <div className="card-header">
            <BookOpen size={20} className="text-accent" />
            <h3>Chunk Inspector</h3>
            {selectedDoc && (
              <span className="graph-badge">{selectedDoc.name}</span>
            )}
          </div>
          
          <div className="chunk-list-viewport" style={{ flex: 1, overflowY: 'auto', maxHeight: '420px', padding: '1rem' }}>
            {!selectedDoc ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', opacity: 0.4, padding: '3.5rem 0' }}>
                <BookOpen size={48} style={{ marginBottom: '1rem', color: 'var(--text-tertiary)' }} />
                <p style={{ textAlign: 'center', fontSize: '0.9rem' }}>Select a document from the left inventory to inspect its indexing chunks.</p>
              </div>
            ) : loadingChunks ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', padding: '3.5rem 0' }}>
                <Loader size={36} className="spin text-accent" style={{ marginBottom: '1rem' }} />
                <p style={{ fontSize: '0.9rem' }}>Retrieving document chunks from GraphStore...</p>
              </div>
            ) : errorChunks ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#ff6b6b', padding: '3.5rem 0' }}>
                <AlertCircle size={36} style={{ marginBottom: '1rem' }} />
                <p style={{ fontSize: '0.9rem' }}>{errorChunks}</p>
              </div>
            ) : chunks.length === 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', opacity: 0.4, padding: '3.5rem 0' }}>
                <Layers size={36} style={{ marginBottom: '1rem' }} />
                <p style={{ fontSize: '0.9rem' }}>No chunks found for this document.</p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.8rem' }}>
                {chunks.map((c, i) => (
                  <div 
                    key={i} 
                    className="glass-panel" 
                    style={{ 
                      padding: '0.9rem', 
                      border: '1px solid rgba(255, 255, 255, 0.08)', 
                      borderRadius: '6px', 
                      background: 'rgba(255, 255, 255, 0.015)' 
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem', fontSize: '0.72rem', opacity: 0.7 }}>
                      <span style={{ fontWeight: 700, color: 'var(--accent-primary)' }}>CHUNK #{i + 1}</span>
                      <span className="status-tag info" style={{ 
                        margin: 0, 
                        fontSize: '0.65rem',
                        background: 'rgba(255,255,255,0.06)',
                        border: '1px solid rgba(255,255,255,0.1)'
                      }}>Page {c.page || 'N/A'}</span>
                    </div>
                    
                    <p style={{ 
                      fontSize: '0.85rem', 
                      lineHeight: '1.45', 
                      margin: '0 0 0.5rem 0', 
                      color: 'rgba(255, 255, 255, 0.85)', 
                      whiteSpace: 'pre-wrap',
                      background: 'rgba(0,0,0,0.15)',
                      padding: '0.6rem',
                      borderRadius: '4px',
                      borderLeft: '2px solid rgba(255,255,255,0.15)'
                    }}>
                      {c.text}
                    </p>
                    
                    {(c.clause_ref || c.article_ref || c.section) && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginTop: '0.5rem' }}>
                        {c.section && <span style={{ fontSize: '0.65rem', padding: '0.15rem 0.4rem', borderRadius: '4px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', opacity: 0.85 }}>Sec: {c.section}</span>}
                        {c.clause_ref && <span style={{ fontSize: '0.65rem', padding: '0.15rem 0.4rem', borderRadius: '4px', background: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.2)', color: 'var(--accent-primary)' }}>Clause: {c.clause_ref}</span>}
                        {c.article_ref && <span style={{ fontSize: '0.65rem', padding: '0.15rem 0.4rem', borderRadius: '4px', background: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.2)', color: '#10b981' }}>Article: {c.article_ref}</span>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
};

export default Analytics;
