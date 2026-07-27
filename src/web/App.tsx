import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactFlow, {
  Background,
  ConnectionMode,
  Controls,
  MarkerType,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type ReactFlowInstance,
  type XYPosition
} from 'reactflow';
import type { DayDiagram, DaySummary, RelationshipEvidence } from '../shared/types';
import { connectionProblem } from '../shared/graph';
import { api } from './api';
import { DayNode, type DayNodeData } from './DayNode';
import { EvidenceWorkspace, type EvidenceTab } from './EvidencePanels';
import { GraphLogo, Icon } from './Icons';
import { NodeLogo } from './NodeLogo';

type FlowNode = Node<DayNodeData, 'dayNode'>;
type ExplorerView = 'dag' | 'timelines' | 'evidence' | 'data' | 'settings';

const nodeColors: DayNodeData['color'][] = ['green', 'blue', 'orange', 'violet', 'rose', 'slate'];
const edgeDefaults = {
  type: 'bezier',
  interactionWidth: 24,
  markerEnd: { type: MarkerType.ArrowClosed, color: '#7c8aa5', width: 18, height: 18 },
  style: { stroke: '#aab4c7', strokeWidth: 1.8 }
};

function toFlow(day: DayDiagram, onRename: (id: string, label: string) => void): { nodes: FlowNode[]; edges: Edge[] } {
  return {
    nodes: day.nodes.map((node) => ({
      id: node.id,
      type: 'dayNode',
      data: {
        label: node.label,
        onRename,
        ...(node.sourceEntityId ? { sourceEntityId: node.sourceEntityId } : {}),
        ...(node.observedSummary ? { observedSummary: node.observedSummary } : {}),
        ...(node.color ? { color: node.color } : {}),
        ...(node.icon ? { icon: node.icon } : {})
      },
      position: { x: node.x, y: node.y }
    })),
    edges: day.edges.map(({ rationale, ...edge }) => ({
      ...edge,
      ...edgeDefaults,
      ...(rationale ? { data: { rationale } } : {})
    }))
  };
}

function selectedRelationship(day: DayDiagram | null, edgeId?: string): RelationshipEvidence | undefined {
  return day?.evidence?.relationships?.find((relationship) => relationship.edgeId === edgeId);
}

function downloadJson(day: DayDiagram) {
  const blob = new Blob([`${JSON.stringify(day, null, 2)}\n`], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${day.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'day-diagram'}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

export function App() {
  const [days, setDays] = useState<DaySummary[]>([]);
  const [day, setDay] = useState<DayDiagram | null>(null);
  const [nodes, setNodes] = useState<FlowNode[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [flow, setFlow] = useState<ReactFlowInstance | null>(null);
  const [view, setView] = useState<ExplorerView>('dag');
  const [evidenceTab, setEvidenceTab] = useState<EvidenceTab>('pattern');
  const [selectedEdgeId, setSelectedEdgeId] = useState<string>();
  const [selectedNodeId, setSelectedNodeId] = useState<string>();
  const [editor, setEditor] = useState<{ kind: 'newDay' | 'renameDay' | 'renameNode'; title: string; value: string; id?: string } | null>(null);
  const nodeTypes = useMemo(() => ({ dayNode: DayNode }), []);
  const connectionMade = useRef(false);
  const rejectedConnection = useRef<string | null>(null);
  const openDayRequest = useRef(0);

  const showNodeEditor = useCallback((id: string, label: string) => {
    setEditor({ kind: 'renameNode', title: 'Rename box', value: label, id });
  }, []);
  const refresh = useCallback(async () => setDays(await api.list()), []);

  const openDay = useCallback(async (id: string, force = false) => {
    if (!force && dirty && !confirm('Discard unsaved changes and switch days?')) return;
    const request = ++openDayRequest.current;
    try {
      const loaded = await api.get(id);
      if (request !== openDayRequest.current) return;
      const flowData = toFlow(loaded, showNodeEditor);
      setDay(loaded);
      setNodes(flowData.nodes);
      setEdges(flowData.edges);
      setSelectedEdgeId(loaded.evidence?.relationships?.[0]?.edgeId ?? loaded.edges[0]?.id);
      setSelectedNodeId(undefined);
      setDirty(false);
      setError('');
    } catch (cause) {
      if (request === openDayRequest.current) setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, [dirty, showNodeEditor]);

  useEffect(() => {
    void (async () => {
      try {
        const list = await api.list();
        setDays(list);
        if (list[0]) await openDay(list[0].id, true);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    })();
  }, []);

  const serialize = useCallback((base: DayDiagram): DayDiagram => ({
    ...base,
    nodes: nodes.map((node) => ({
      id: node.id,
      label: node.data.label,
      x: node.position.x,
      y: node.position.y,
      ...(node.data.sourceEntityId ? { sourceEntityId: node.data.sourceEntityId } : {}),
      ...(node.data.observedSummary ? { observedSummary: node.data.observedSummary } : {}),
      ...(node.data.color ? { color: node.data.color } : {}),
      ...(node.data.icon ? { icon: node.data.icon } : {})
    })),
    edges: edges.map(({ id, source, target, sourceHandle, targetHandle, data }) => ({
      id,
      source,
      target,
      ...(sourceHandle ? { sourceHandle } : {}),
      ...(targetHandle ? { targetHandle } : {}),
      ...(typeof data?.rationale === 'string' && data.rationale.trim() ? { rationale: data.rationale.trim() } : {})
    }))
  }), [edges, nodes]);

  const save = useCallback(async () => {
    if (!day || saving) return;
    setSaving(true);
    try {
      const saved = await api.save(serialize(day));
      setDay(saved);
      setDirty(false);
      setError('');
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSaving(false);
    }
  }, [day, refresh, saving, serialize]);

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        void save();
      }
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, [save]);

  const newDay = () => {
    if (dirty && !confirm('Discard unsaved changes and create a new day?')) return;
    setEditor({ kind: 'newDay', title: 'Name the new day', value: 'New Day' });
  };

  const addBox = (position?: XYPosition) => {
    if (!day) return;
    const index = nodes.length + 1;
    const nextPosition = position ?? { x: 100 + ((index - 1) % 3) * 240, y: 90 + Math.floor((index - 1) / 3) * 170 };
    setNodes((current) => [
      ...current.map((node) => ({ ...node, selected: false })),
      {
        id: `node-${crypto.randomUUID()}`,
        type: 'dayNode',
        data: { label: `Box ${index}`, onRename: showNodeEditor, color: nodeColors[(index - 1) % nodeColors.length] },
        position: nextPosition,
        selected: true
      }
    ]);
    setEdges((current) => current.map((edge) => ({ ...edge, selected: false })));
    setSelectedNodeId(undefined);
    setSelectedEdgeId(undefined);
    setDirty(true);
  };

  const renameDay = (summary: DaySummary) => setEditor({ kind: 'renameDay', title: 'Rename day', value: summary.name, id: summary.id });
  const deleteDay = async (summary: DaySummary) => {
    if (!confirm(`Delete "${summary.name}"? This cannot be undone.`)) return;
    try {
      await api.delete(summary.id);
      const list = await api.list();
      setDays(list);
      if (day?.id === summary.id) {
        setDay(null);
        setNodes([]);
        setEdges([]);
        setDirty(false);
        if (list[0]) await openDay(list[0].id, true);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const onNodesChange = (changes: NodeChange[]) => {
    setNodes((current) => applyNodeChanges(changes, current) as FlowNode[]);
    if (changes.some((change) => change.type !== 'select' && change.type !== 'dimensions')) setDirty(true);
    if (changes.some((change) => change.type === 'remove' && change.id === selectedNodeId)) setSelectedNodeId(undefined);
  };
  const onEdgesChange = (changes: EdgeChange[]) => {
    setEdges((current) => applyEdgeChanges(changes, current));
    if (changes.some((change) => change.type !== 'select')) setDirty(true);
    if (changes.some((change) => change.type === 'remove' && change.id === selectedEdgeId)) setSelectedEdgeId(undefined);
  };
  const onConnect = (connection: Connection) => {
    const problem = connectionProblem(edges, connection.source, connection.target);
    if (problem) {
      setError(problem);
      return;
    }
    const id = `edge-${crypto.randomUUID()}`;
    connectionMade.current = true;
    setEdges((current) => addEdge({ ...connection, id, ...edgeDefaults }, current));
    setSelectedEdgeId(id);
    setSelectedNodeId(undefined);
    setDirty(true);
    setError('');
  };
  const isValidConnection = useCallback((connection: Connection) => {
    const problem = connectionProblem(edges, connection.source, connection.target);
    rejectedConnection.current = problem;
    return problem === null;
  }, [edges]);
  const clear = () => {
    if (day && confirm(`Clear every box and edge from "${day.name}"?`)) {
      setNodes([]);
      setEdges([]);
      setSelectedEdgeId(undefined);
      setSelectedNodeId(undefined);
      setDirty(true);
    }
  };

  const submitEditor = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editor) return;
    const value = editor.value.trim();
    if (!value) {
      setError('A name cannot be blank.');
      return;
    }
    try {
      if (editor.kind === 'newDay') {
        const created = await api.create(value);
        await refresh();
        await openDay(created.id, true);
      } else if (editor.kind === 'renameNode' && editor.id) {
        setNodes((current) => current.map((item) => item.id === editor.id ? { ...item, data: { ...item.data, label: value } } : item));
        setDirty(true);
      } else if (editor.kind === 'renameDay' && editor.id) {
        const loaded = day?.id === editor.id && day ? serialize(day) : await api.get(editor.id);
        const saved = await api.save({ ...loaded, name: value });
        if (day?.id === saved.id) {
          setDay(saved);
          setDirty(false);
        }
        await refresh();
      }
      setEditor(null);
      setError('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const currentSnapshot = day ? serialize(day) : null;
  const selectedEdge = edges.find((edge) => edge.id === selectedEdgeId);
  const selectedNode = nodes.find((node) => node.id === selectedNodeId);
  const relationship = selectedRelationship(day, selectedEdgeId);

  const navigate = (next: ExplorerView) => {
    setView(next);
    if (next === 'timelines') setEvidenceTab('timeline');
    if (next === 'evidence') setEvidenceTab('pattern');
  };

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><GraphLogo /><div><strong>MCP</strong><small>Day DAG Explorer</small></div></div>
      <nav className="primary-nav" aria-label="Explorer sections">
        <NavButton icon="graph" label="DAG View" active={view === 'dag'} onClick={() => navigate('dag')} />
        <NavButton icon="timeline" label="Timelines" active={view === 'timelines'} onClick={() => navigate('timelines')} />
        <NavButton icon="evidence" label="Evidence" active={view === 'evidence'} onClick={() => navigate('evidence')} />
        <NavButton icon="data" label="Data" active={view === 'data'} onClick={() => navigate('data')} />
        <NavButton icon="settings" label="Settings" active={view === 'settings'} onClick={() => navigate('settings')} />
      </nav>

      <div className="day-library">
        <div className="library-heading"><span>Saved days</span><button type="button" title="New Day" aria-label="New Day" onClick={newDay}><Icon name="plus" size={17} /></button></div>
        <button className="new-day" onClick={newDay}><Icon name="plus" size={17} /> New Day</button>
        <div className="day-list" aria-label="Saved days">
          {days.map((summary) => <div key={summary.id} className={`day-row${day?.id === summary.id ? ' active' : ''}`}>
            <button className="day-open" onClick={() => void openDay(summary.id)} onDoubleClick={() => renameDay(summary)}><span>{summary.name}</span><small>{new Date(summary.updatedAt).toLocaleDateString()}</small></button>
            <button className="icon-button" title="Rename day" aria-label={`Rename ${summary.name}`} onClick={() => renameDay(summary)}><Icon name="edit" size={14} /></button>
            <button className="icon-button danger" title="Delete day" aria-label={`Delete ${summary.name}`} onClick={() => void deleteDay(summary)}><Icon name="trash" size={14} /></button>
          </div>)}
          {!days.length && <p className="empty-list">No saved days yet.</p>}
        </div>
      </div>

      <div className="local-card"><Icon name="data" size={24} /><div><strong>Local by design</strong><span>Diagrams stay in your JSON file. No account or cloud service is required.</span></div></div>
    </aside>

    <main className="workspace">
      <header className="page-header">
        <div><h1>Causal DAG Explorer <span>✦</span></h1><p>Build and inspect directed hypotheses from manually supplied evidence.</p></div>
        <button className="export-button" disabled={!currentSnapshot} onClick={() => currentSnapshot && downloadJson(currentSnapshot)}><Icon name="save" size={16} /> Export JSON</button>
      </header>

      {error && <div className="error-banner" role="alert"><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError('')}><Icon name="close" size={16} /></button></div>}

      <div className="content-scroll">
        <header className="toolbar">
          <div className="title-wrap">
            <div><small>Current day</small><h2>{day?.name ?? 'Choose or create a day'}</h2></div>
            {day?.evidence && <span className="evidence-badge" title={`${day.evidence.question}\n${day.evidence.entityIds.join(', ')}`}>{day.evidence.provider === 'ha_unofficial_ai' ? 'HA evidence' : 'Synthetic example'}</span>}
            {dirty && <span className="unsaved" data-testid="unsaved-indicator"><i /> Unsaved changes</span>}
          </div>
          <div className="toolbar-actions">
            <button disabled={!day} onClick={clear}>Clear Canvas</button>
            <button data-testid="add-box" disabled={!day} onClick={() => addBox()}><Icon name="plus" size={17} /> Add Box</button>
            <button className="save" data-testid="save-day" disabled={!day || saving} onClick={() => void save()}><Icon name="save" size={16} /> {saving ? 'Saving…' : 'Save'}</button>
          </div>
        </header>

        {!day ? <section className="welcome">
          <div className="welcome-icon"><Icon name="graph" size={42} /></div>
          <h2>Create your first day</h2>
          <p>Add boxes, connect them, and arrange a directed acyclic graph.</p>
          <button className="save" onClick={newDay}>New Day</button>
        </section> : <>
          {view === 'dag' && <div className="dag-view">
            <div className="dag-grid">
              <section className="diagram-card" aria-label="DAG diagram card">
                <div className="card-heading"><div><h3>Causal DAG</h3><span title="Arrows are editable hypotheses, not proof of causation."><Icon name="info" size={15} /></span></div><small>{nodes.length} boxes · {edges.length} directed edges</small></div>
                <div className="canvas" aria-label="Day diagram canvas">
                  <ReactFlow
                    key={day.id}
                    nodes={nodes}
                    edges={edges}
                    nodeTypes={nodeTypes}
                    onInit={setFlow}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    onConnect={onConnect}
                    isValidConnection={isValidConnection}
                    onConnectStart={() => { connectionMade.current = false; rejectedConnection.current = null; setError(''); }}
                    onConnectEnd={() => { if (!connectionMade.current && rejectedConnection.current) setError(rejectedConnection.current); }}
                    onDoubleClick={(event) => {
                      const target = event.target as HTMLElement;
                      if (flow && target.classList.contains('react-flow__pane')) addBox(flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
                    }}
                    onNodeDoubleClick={(_event, node) => showNodeEditor(node.id, node.data.label)}
                    onNodeClick={(_event, node) => { setSelectedNodeId(node.id); setSelectedEdgeId(undefined); }}
                    onEdgeClick={(_event, edge) => { setSelectedEdgeId(edge.id); setSelectedNodeId(undefined); }}
                    onPaneClick={() => { setSelectedEdgeId(undefined); setSelectedNodeId(undefined); }}
                    fitView
                    fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
                    minZoom={0.2}
                    maxZoom={2}
                    deleteKeyCode={['Backspace', 'Delete']}
                    defaultEdgeOptions={edgeDefaults}
                    connectionMode={ConnectionMode.Loose}
                    connectionRadius={28}
                    snapToGrid
                    snapGrid={[10, 10]}
                    selectionOnDrag
                  >
                    <Background color="#d8dfec" gap={22} size={1} />
                    <Controls showInteractive={false} />
                  </ReactFlow>
                </div>
                <div className="diagram-legend"><span><i className="selected-edge-key" /> Selected edge</span><span><i className="edge-key" /> Other edges</span><span>Drag a handle to connect</span></div>
              </section>

              <SelectionInspector
                day={currentSnapshot!}
                edge={selectedEdge}
                node={selectedNode}
                relationship={relationship}
                onClose={() => { setSelectedEdgeId(undefined); setSelectedNodeId(undefined); }}
                onRationaleChange={(value) => {
                  if (!selectedEdgeId) return;
                  setEdges((current) => current.map((edge) => edge.id === selectedEdgeId ? { ...edge, data: { ...edge.data, rationale: value } } : edge));
                  setDirty(true);
                }}
              />
            </div>
            <EvidenceWorkspace day={currentSnapshot!} selectedEdgeId={selectedEdgeId} tab={evidenceTab} onTabChange={setEvidenceTab} />
          </div>}

          {(view === 'timelines' || view === 'evidence') && <div className="standalone-panel"><EvidenceWorkspace day={currentSnapshot!} selectedEdgeId={selectedEdgeId} tab={evidenceTab} onTabChange={setEvidenceTab} /></div>}
          {view === 'data' && <DataView day={currentSnapshot!} />}
          {view === 'settings' && <SettingsView day={currentSnapshot!} />}
        </>}
      </div>
    </main>

    {editor && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setEditor(null); }}>
      <form className="name-modal" role="dialog" aria-modal="true" aria-labelledby="editor-title" onSubmit={(event) => void submitEditor(event)}>
        <h2 id="editor-title">{editor.title}</h2>
        <label htmlFor="name-editor">Name</label>
        <input id="name-editor" autoFocus maxLength={editor.kind === 'renameNode' ? 120 : 100} value={editor.value} onChange={(event) => setEditor({ ...editor, value: event.target.value })} />
        <div className="modal-actions"><button type="button" onClick={() => setEditor(null)}>Cancel</button><button className="save" type="submit">{editor.kind === 'newDay' ? 'Create Day' : 'Rename'}</button></div>
      </form>
    </div>}
  </div>;
}

function NavButton({ icon, label, active, onClick }: { icon: 'graph' | 'timeline' | 'evidence' | 'data' | 'settings'; label: string; active: boolean; onClick: () => void }) {
  return <button className={active ? 'active' : ''} aria-label={label} title={label} aria-current={active ? 'page' : undefined} onClick={onClick}><Icon name={icon} size={20} /><span>{label}</span></button>;
}

function SelectionInspector({ day, edge, node, relationship, onClose, onRationaleChange }: {
  day: DayDiagram;
  edge?: Edge;
  node?: FlowNode;
  relationship?: RelationshipEvidence;
  onClose: () => void;
  onRationaleChange: (value: string) => void;
}) {
  if (node) {
    return <aside className="inspector-card" aria-label="Selected box details">
      <div className="inspector-title"><div><small>Selected box</small><h3>{node.data.label}</h3></div><button aria-label="Close inspector" onClick={onClose}><Icon name="close" size={17} /></button></div>
      <NodeLogo className="node-detail-icon" label={node.data.label} icon={node.data.icon} />
      <dl className="detail-list"><div><dt>Position</dt><dd>{Math.round(node.position.x)}, {Math.round(node.position.y)}</dd></div><div><dt>Source entity</dt><dd>{node.data.sourceEntityId ?? 'Manual box'}</dd></div></dl>
      <div className="inspector-note"><Icon name="info" size={18} /><p>{node.data.observedSummary ?? 'No observed summary has been supplied for this box.'}</p></div>
      <button className="inspector-action" onClick={() => node.data.onRename?.(node.id, node.data.label)}><Icon name="edit" size={15} /> Rename box</button>
    </aside>;
  }

  if (!edge) {
    return <aside className="inspector-card empty-inspector" aria-label="Selection details">
      <div className="empty-inspector-icon"><Icon name="link" size={28} /></div>
      <h3>Select a relationship</h3>
      <p>Click an arrow to see its rationale, provenance, and any saved day-level evidence.</p>
      <ul><li>Arrow direction is explicit</li><li>Relationships remain editable hypotheses</li><li>No causal claim is generated automatically</li></ul>
    </aside>;
  }

  const source = day.nodes.find((item) => item.id === edge.source)?.label ?? edge.source;
  const target = day.nodes.find((item) => item.id === edge.target)?.label ?? edge.target;
  const supportCount = relationship?.supportCount ?? relationship?.daily?.filter((point) => point.support === 'supportive').length;
  const totalCount = relationship?.totalCount ?? relationship?.daily?.length;
  const percent = supportCount !== undefined && totalCount ? Math.round((supportCount / totalCount) * 100) : undefined;

  return <aside className="inspector-card" aria-label="Selected relationship details">
    <div className="inspector-title"><div><small>Selected relationship</small><h3>{source} <span>→</span> {target}</h3></div><button aria-label="Close inspector" onClick={onClose}><Icon name="close" size={17} /></button></div>
    <span className="selection-pill"><Icon name="link" size={13} /> Edge selected</span>
    <div className="relationship-summary"><Icon name="evidence" size={22} /><p>{relationship?.summary ?? (typeof edge.data?.rationale === 'string' ? edge.data.rationale : 'Add a rationale for this directed relationship.')}</p></div>
    {percent !== undefined && <div className="support-row">
      <div className="support-ring" style={{ '--support': `${percent * 3.6}deg` } as React.CSSProperties}><strong>{percent}%</strong></div>
      <div><strong>{supportCount} / {totalCount} observations</strong><span>classified as supportive</span></div>
    </div>}
    <dl className="detail-list">
      <div><dt>Average lag</dt><dd>{relationship?.averageLag ?? 'Not supplied'}</dd></div>
      <div><dt>Strength label</dt><dd>{relationship?.strengthLabel ?? 'Exploratory'}</dd></div>
      <div><dt>Consistency</dt><dd>{relationship?.consistencyLabel ?? 'Not supplied'}</dd></div>
      <div><dt>Meaning</dt><dd>{relationship?.interpretation ?? 'A direction to inspect, not proof of causation.'}</dd></div>
    </dl>
    <label className="rationale-editor">Relationship rationale<textarea value={typeof edge.data?.rationale === 'string' ? edge.data.rationale : ''} maxLength={500} placeholder="Why is this arrow worth inspecting?" onChange={(event) => onRationaleChange(event.target.value)} /></label>
  </aside>;
}

function DataView({ day }: { day: DayDiagram }) {
  return <section className="page-card data-view">
    <div className="section-heading"><div><h3>Diagram data</h3><p>Compact local records used by the editor. Credentials and raw Home Assistant payloads are never stored.</p></div><span className="safe-label">{day.nodes.length} boxes</span></div>
    <div className="data-table-wrap"><table><thead><tr><th>Box</th><th>Position</th><th>Source entity</th><th>Observed summary</th></tr></thead><tbody>
      {day.nodes.map((node) => <tr key={node.id}><td><strong>{node.label}</strong><small>{node.id}</small></td><td>{Math.round(node.x)}, {Math.round(node.y)}</td><td>{node.sourceEntityId ?? 'Manual'}</td><td>{node.observedSummary ?? '—'}</td></tr>)}
    </tbody></table></div>
    <div className="notes-card"><h4>Provenance and limitations</h4>{day.evidence?.notes.length ? <ul>{day.evidence.notes.map((note, index) => <li key={index}>{note}</li>)}</ul> : <p>No evidence notes supplied.</p>}</div>
  </section>;
}

function SettingsView({ day }: { day: DayDiagram }) {
  return <section className="settings-grid">
    <article className="page-card"><Icon name="data" size={25} /><h3>Local persistence</h3><p>Save writes this day to the configured local JSON file using an atomic replace.</p><dl className="detail-list"><div><dt>Day ID</dt><dd>{day.id}</dd></div><div><dt>Last saved</dt><dd>{new Date(day.updatedAt).toLocaleString()}</dd></div></dl></article>
    <article className="page-card"><Icon name="graph" size={25} /><h3>DAG safeguards</h3><p>Self-edges, duplicate source-target pairs, missing endpoints, and directed cycles are rejected.</p><span className="settings-status">Enabled</span></article>
    <article className="page-card"><Icon name="evidence" size={25} /><h3>Evidence boundary</h3><p>Charts appear only when bounded summaries are explicitly supplied. The app does not infer effects, fit models, or invent missing observations.</p><span className="settings-status">Observation only</span></article>
  </section>;
}
