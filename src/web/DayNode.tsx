import { Handle, Position, type NodeProps } from 'reactflow';

export interface DayNodeData {
  label: string;
  onRename?: (id: string, label: string) => void;
  sourceEntityId?: string;
  observedSummary?: string;
  color?: 'blue' | 'green' | 'violet' | 'orange' | 'rose' | 'slate';
  icon?: string;
}

export function DayNode({ id, data, selected }: NodeProps<DayNodeData>) {
  const rename = (event: React.MouseEvent) => {
    event.stopPropagation();
    data.onRename?.(id, data.label);
  };
  const details = ['Double-click to rename', data.sourceEntityId, data.observedSummary].filter(Boolean).join('\n');
  const color = data.color ?? 'blue';
  return <div className={`day-node color-${color}${selected ? ' selected' : ''}`} data-node-id={id} title={details} onDoubleClick={rename}>
    <button className="node-rename nodrag nopan" type="button" aria-label={`Rename ${data.label}`} title="Rename box" onClick={rename}>✎</button>
    <Handle type="source" position={Position.Left} id="left" className="connection-handle handle-left" aria-label={`Connect from ${data.label} left`} />
    <Handle type="source" position={Position.Top} id="top" className="connection-handle handle-top" aria-label={`Connect from ${data.label} top`} />
    <span className="node-icon" aria-hidden="true">{data.icon ?? data.label.slice(0, 1).toUpperCase()}</span>
    <span className="node-label">{data.label}</span>
    {data.sourceEntityId && <span className="ha-node-badge" aria-label={`Home Assistant source ${data.sourceEntityId}`}>HA</span>}
    <Handle type="source" position={Position.Right} id="right" className="connection-handle handle-right" aria-label={`Connect from ${data.label} right`} />
    <Handle type="source" position={Position.Bottom} id="bottom" className="connection-handle handle-bottom" aria-label={`Connect from ${data.label} bottom`} />
  </div>;
}
