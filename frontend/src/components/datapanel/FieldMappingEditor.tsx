import { useState, useEffect } from 'react';

interface FieldMappingEditorProps {
  sourceId: number;
  sourceName: string;
  existingMapping: Record<string, string>;
  onClose: () => void;
  onSave: (mapping: Record<string, string>) => void;
}

interface ColumnInfo {
  name: string;
  dtype: string;
  samples: string[];
}

const CANONICAL_FIELDS = [
  'geometry', 'name', 'id', 'area', 'perimeter', 'population',
  'land_use', 'land_type', 'elevation', 'slope', 'ndvi',
  'temperature', 'precipitation', 'district', 'province', 'city',
  'county', 'address', 'latitude', 'longitude', 'date', 'year',
  'source', 'category', 'description', 'status', 'owner', 'code',
  'value', 'unit', 'building_area', 'road_name', 'water_body',
  'soil_type', 'vegetation',
];

export default function FieldMappingEditor({
  sourceId, sourceName, existingMapping, onClose, onSave,
}: FieldMappingEditorProps) {
  const [columns, setColumns] = useState<ColumnInfo[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({ ...existingMapping });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [inferring, setInferring] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState('');
  const [autoFilled, setAutoFilled] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchColumns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceId]);

  const fetchColumns = async () => {
    setLoading(true);
    setError('');
    try {
      const r = await fetch(`/api/virtual-sources/${sourceId}/preview-columns`, {
        method: 'POST', credentials: 'include',
      });
      if (!r.ok) { setError('获取列信息失败'); return; }
      const d = await r.json();
      const cols: ColumnInfo[] = d.columns || [];
      setColumns(cols);
      // Initialize mapping entries for columns not already in existingMapping
      const init: Record<string, string> = { ...existingMapping };
      for (const c of cols) {
        if (!(c.name in init)) init[c.name] = '';
      }
      setMapping(init);
    } catch { setError('网络错误，无法获取列信息'); }
    finally { setLoading(false); }
  };

  const handleInfer = async () => {
    setInferring(true);
    setError('');
    try {
      const r = await fetch(`/api/virtual-sources/${sourceId}/infer-mapping`, {
        method: 'POST', credentials: 'include',
      });
      if (!r.ok) { setError('自动推断失败'); return; }
      const d = await r.json();
      const inferred: Record<string, string> = d.mapping || {};
      const filled = new Set<string>();
      const next = { ...mapping };
      for (const [remote, target] of Object.entries(inferred)) {
        if (target && CANONICAL_FIELDS.includes(target)) {
          next[remote] = target;
          filled.add(remote);
        }
      }
      setMapping(next);
      setAutoFilled(filled);
    } catch { setError('网络错误，推断请求失败'); }
    finally { setInferring(false); }
  };

  const handleClearAll = () => {
    const cleared: Record<string, string> = {};
    for (const key of Object.keys(mapping)) cleared[key] = '';
    setMapping(cleared);
    setAutoFilled(new Set());
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    setSavedMsg('');
    // Build only non-empty entries
    const payload: Record<string, string> = {};
    let count = 0;
    for (const [remote, target] of Object.entries(mapping)) {
      if (target) { payload[remote] = target; count++; }
    }
    try {
      const r = await fetch(`/api/virtual-sources/${sourceId}/schema-mapping`, {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schema_mapping: payload }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setError(d.error || '保存失败');
        return;
      }
      setSavedMsg(`已保存 ${count} 个映射`);
      setTimeout(() => setSavedMsg(''), 2000);
      onSave(payload);
    } catch { setError('网络错误，保存失败'); }
    finally { setSaving(false); }
  };

  const setField = (remote: string, target: string) => {
    setMapping(prev => ({ ...prev, [remote]: target }));
    setAutoFilled(prev => { const n = new Set(prev); n.delete(remote); return n; });
  };

  const truncate = (s: string, max = 20) => s.length > max ? s.slice(0, max) + '...' : s;

  // --- styles ---
  const overlay: React.CSSProperties = {
    position: 'fixed', inset: 0, zIndex: 9999,
    background: 'rgba(0,0,0,0.55)', display: 'flex',
    alignItems: 'center', justifyContent: 'center',
  };
  const modal: React.CSSProperties = {
    background: '#131620', border: '1px solid #2d3348', borderRadius: 10,
    width: '100%', maxWidth: 700, maxHeight: '80vh',
    display: 'flex', flexDirection: 'column', color: '#e0e0e0',
    boxShadow: '0 8px 32px rgba(0,0,0,0.45)',
  };
  const header: React.CSSProperties = {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '14px 20px', borderBottom: '1px solid #2d3348', flexShrink: 0,
  };
  const body: React.CSSProperties = {
    flex: 1, overflowY: 'auto', padding: '12px 20px',
  };
  const footer: React.CSSProperties = {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '12px 20px', borderTop: '1px solid #2d3348', flexShrink: 0, gap: 8,
  };
  const thStyle: React.CSSProperties = {
    textAlign: 'left', padding: '6px 8px', fontSize: 12,
    color: '#888', fontWeight: 600, borderBottom: '1px solid #2d3348',
  };
  const tdStyle: React.CSSProperties = {
    padding: '5px 8px', fontSize: 13, borderBottom: '1px solid #1e2233',
    verticalAlign: 'middle',
  };
  const badge: React.CSSProperties = {
    display: 'inline-block', fontSize: 10, padding: '1px 5px', borderRadius: 3,
    background: '#262d3d', color: '#8892a8', fontFamily: 'monospace',
  };
  const selectBase: React.CSSProperties = {
    background: '#0d1117', border: '1px solid #444', borderRadius: 4,
    padding: '3px 6px', color: '#e0e0e0', fontSize: 12, width: '100%',
  };
  const btnPrimary: React.CSSProperties = {
    fontSize: 12, padding: '5px 14px', borderRadius: 4, border: 'none',
    background: '#2563eb', color: '#fff', cursor: 'pointer', fontWeight: 600,
  };
  const btnSecondary: React.CSSProperties = {
    fontSize: 12, padding: '5px 14px', borderRadius: 4,
    background: 'transparent', border: '1px solid #444',
    color: '#aaa', cursor: 'pointer',
  };

  return (
    <div style={overlay} onClick={onClose}>
      <div style={modal} onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div style={header}>
          <span style={{ fontWeight: 700, fontSize: 15 }}>
            字段映射 &mdash; {sourceName}
          </span>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', color: '#888',
            fontSize: 20, cursor: 'pointer', lineHeight: 1,
          }}>&times;</button>
        </div>

        {/* Body */}
        <div style={body}>
          {loading && (
            <div style={{ textAlign: 'center', padding: 32, color: '#888' }}>
              <span style={{ display: 'inline-block', animation: 'spin 1s linear infinite',
                border: '2px solid #333', borderTop: '2px solid #2563eb',
                borderRadius: '50%', width: 20, height: 20 }} />
              <div style={{ marginTop: 8 }}>加载列信息...</div>
            </div>
          )}

          {!loading && error && !columns.length && (
            <div style={{ color: '#ef4444', textAlign: 'center', padding: 24 }}>{error}</div>
          )}

          {!loading && !error && columns.length === 0 && (
            <div style={{ color: '#888', textAlign: 'center', padding: 24 }}>
              无法获取远程列信息
            </div>
          )}

          {!loading && columns.length > 0 && (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={thStyle}>远程字段</th>
                  <th style={thStyle}>类型</th>
                  <th style={thStyle}>示例值</th>
                  <th style={{ ...thStyle, width: 24, textAlign: 'center' }}></th>
                  <th style={thStyle}>映射目标</th>
                </tr>
              </thead>
              <tbody>
                {columns.map(col => {
                  const sample = col.samples?.length ? col.samples[0] : '';
                  const isAuto = autoFilled.has(col.name);
                  return (
                    <tr key={col.name}>
                      <td style={tdStyle}>
                        <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{col.name}</span>
                      </td>
                      <td style={tdStyle}>
                        <span style={badge}>{col.dtype}</span>
                      </td>
                      <td style={{ ...tdStyle, color: '#888', fontSize: 12, maxWidth: 120,
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={sample}>
                        {truncate(sample)}
                      </td>
                      <td style={{ ...tdStyle, textAlign: 'center', color: '#555', fontSize: 14 }}>
                        &rarr;
                      </td>
                      <td style={tdStyle}>
                        <select
                          value={mapping[col.name] || ''}
                          onChange={e => setField(col.name, e.target.value)}
                          style={{
                            ...selectBase,
                            ...(isAuto ? { borderColor: '#2563eb', color: '#60a5fa' } : {}),
                          }}
                        >
                          <option value="">(空/不映射)</option>
                          {CANONICAL_FIELDS.map(f => (
                            <option key={f} value={f}>{f}</option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          {error && columns.length > 0 && (
            <div style={{ color: '#ef4444', fontSize: 12, marginTop: 8 }}>{error}</div>
          )}

          {savedMsg && (
            <div style={{ color: '#10b981', fontSize: 12, marginTop: 8, fontWeight: 600 }}>
              {savedMsg}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={footer}>
          <div style={{ display: 'flex', gap: 8 }}>
            <button style={btnSecondary} onClick={handleInfer} disabled={inferring || loading}>
              {inferring ? '推断中...' : '自动推断'}
            </button>
            <button style={btnSecondary} onClick={handleClearAll} disabled={loading}>
              清除全部
            </button>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button style={btnSecondary} onClick={onClose}>取消</button>
            <button style={{ ...btnPrimary, ...(saving ? { opacity: 0.7 } : {}) }}
              onClick={handleSave} disabled={saving || loading}>
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
