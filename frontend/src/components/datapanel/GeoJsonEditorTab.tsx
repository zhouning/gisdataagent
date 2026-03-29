import { useState } from 'react';

export default function GeoJsonEditorTab() {
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [saving, setSaving] = useState(false);

  const validate = () => {
    setError('');
    setInfo('');
    if (!text.trim()) { setError('请粘贴 GeoJSON 内容'); return null; }
    try {
      const parsed = JSON.parse(text);
      if (!parsed.type) { setError('缺少 "type" 字段'); return null; }
      if (parsed.type === 'FeatureCollection') {
        const n = parsed.features?.length || 0;
        setInfo(`FeatureCollection: ${n} 个要素`);
      } else if (parsed.type === 'Feature') {
        setInfo(`单个 Feature (${parsed.geometry?.type || 'unknown'})`);
      } else {
        setInfo(`类型: ${parsed.type}`);
      }
      return parsed;
    } catch (e: any) {
      setError(`JSON 解析错误: ${e.message}`);
      return null;
    }
  };

  const handleSave = async () => {
    const parsed = validate();
    if (!parsed) return;
    setSaving(true);
    try {
      const blob = new Blob([JSON.stringify(parsed, null, 2)], { type: 'application/json' });
      const formData = new FormData();
      const filename = `geojson_${Date.now()}.geojson`;
      formData.append('file', blob, filename);
      const r = await fetch('/api/user/upload', { method: 'POST', credentials: 'include', body: formData });
      if (r.ok) {
        setInfo(`已保存为 ${filename}`);
        setError('');
      } else {
        setError('保存失败');
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleFormat = () => {
    try {
      const parsed = JSON.parse(text);
      setText(JSON.stringify(parsed, null, 2));
      setError('');
    } catch (e: any) {
      setError(`格式化失败: ${e.message}`);
    }
  };

  return (
    <div style={{ padding: '8px 12px', fontSize: 13, display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ fontWeight: 600 }}>GeoJSON 编辑器</span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button className="btn-secondary btn-sm" onClick={validate} style={{ fontSize: 11 }}>验证</button>
          <button className="btn-secondary btn-sm" onClick={handleFormat} style={{ fontSize: 11 }}>格式化</button>
          <button className="btn-primary btn-sm" onClick={handleSave} disabled={saving} style={{ fontSize: 11 }}>
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
      {error && <div style={{ color: '#ef4444', fontSize: 12, marginBottom: 4 }}>{error}</div>}
      {info && <div style={{ color: '#10b981', fontSize: 12, marginBottom: 4 }}>{info}</div>}
      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder='粘贴或编辑 GeoJSON 内容...\n\n{\n  "type": "FeatureCollection",\n  "features": []\n}'
        style={{
          flex: 1, minHeight: 200, background: '#0d1117', border: '1px solid #333',
          borderRadius: 6, padding: 8, color: '#e0e0e0', fontFamily: 'monospace',
          fontSize: 12, resize: 'vertical', lineHeight: 1.5,
        }}
      />
    </div>
  );
}
