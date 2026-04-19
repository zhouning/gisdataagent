import { Handle, Position } from '@xyflow/react';

// Edge style constants
export const INHERITS_EDGE_STYLE = { stroke: '#3b82f6', strokeWidth: 2 };
export const ASSOCIATES_EDGE_STYLE = { stroke: '#f59e0b', strokeWidth: 1.5, strokeDasharray: '5 3' };

interface UmlClassNodeData {
  label: string;
  attributes?: { name: string; type: string }[];
  classId?: string;
}

export function UmlClassNode({ data }: { data: UmlClassNodeData }) {
  const attrs = data.attributes || [];
  const visible = attrs.slice(0, 5);
  const overflow = attrs.length - 5;

  return (
    <div style={{
      background: '#fff',
      border: '1px solid #3b82f6',
      borderLeft: '4px solid #3b82f6',
      borderRadius: 6,
      minWidth: 160,
      maxWidth: 220,
      fontSize: 12,
      boxShadow: '0 1px 4px rgba(0,0,0,0.1)',
    }}>
      <Handle type="target" position={Position.Top} style={{ background: '#3b82f6' }} />
      <div style={{
        padding: '6px 10px',
        fontWeight: 700,
        color: '#1e40af',
        borderBottom: visible.length > 0 ? '1px solid #dbeafe' : 'none',
        wordBreak: 'break-word',
      }}>
        {data.label}
      </div>
      {visible.length > 0 && (
        <div style={{ padding: '4px 10px 6px' }}>
          {visible.map((a, i) => (
            <div key={i} style={{ color: '#374151', lineHeight: '1.6', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              <span style={{ color: '#6b7280' }}>{a.name}</span>
              <span style={{ color: '#9ca3af' }}>: </span>
              <span style={{ color: '#1d4ed8' }}>{a.type}</span>
            </div>
          ))}
          {overflow > 0 && (
            <div style={{ color: '#9ca3af', fontSize: 11, marginTop: 2 }}>+{overflow} more</div>
          )}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} style={{ background: '#3b82f6' }} />
    </div>
  );
}

interface UmlModuleNodeData {
  label: string;
  classCount?: number;
}

export function UmlModuleNode({ data }: { data: UmlModuleNodeData }) {
  return (
    <div style={{
      background: '#f5f3ff',
      border: '2px dashed #8b5cf6',
      borderRadius: 8,
      padding: '8px 14px',
      minWidth: 140,
      fontSize: 12,
      display: 'flex',
      alignItems: 'center',
      gap: 8,
    }}>
      <Handle type="target" position={Position.Top} style={{ background: '#8b5cf6' }} />
      <span style={{ fontWeight: 600, color: '#5b21b6' }}>{data.label}</span>
      {data.classCount !== undefined && (
        <span style={{
          background: '#8b5cf6',
          color: '#fff',
          borderRadius: 10,
          padding: '1px 7px',
          fontSize: 11,
          fontWeight: 600,
        }}>
          {data.classCount}
        </span>
      )}
      <Handle type="source" position={Position.Bottom} style={{ background: '#8b5cf6' }} />
    </div>
  );
}

export const umlNodeTypes = {
  umlClass: UmlClassNode,
  umlModule: UmlModuleNode,
};
